import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock
import io

# Modify path to include parent dir
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.logger import TelegramLogger

class TestTelegramLogger(unittest.TestCase):
    def setUp(self):
        self.mock_client = AsyncMock()
        self.channel_id = 12345
        self.logger = TelegramLogger(self.mock_client, self.channel_id)
        
        # Save real stdout/stderr
        self.real_stdout = sys.stdout
        self.real_stderr = sys.stderr
        
        # Mock original streams for the logger instance slightly differently
        # We want capturing to divert to stringIO, but we need to respect the architecture
        self.logger.original_stdout = io.StringIO()
        self.logger.original_stderr = io.StringIO()
        self.logger.FLUSH_INTERVAL = 0.1

    def tearDown(self):
        # Ensure global streams are restored to real ones
        sys.stdout = self.real_stdout
        sys.stderr = self.real_stderr

    def test_buffer_add(self):
        self.logger._add_to_buffer("test log")
        self.assertIn("test log", self.logger.buffer)

    async def test_flush(self):
        self.logger._add_to_buffer("log 1")
        self.logger._add_to_buffer("log 2")
        await self.logger.flush()
        
        # Verify client.send_message called
        self.mock_client.send_message.assert_called_once()
        args = self.mock_client.send_message.call_args[0]
        self.assertEqual(args[0], self.channel_id)
        self.assertIn("log 1", args[1])
        self.assertIn("log 2", args[1])
        self.assertTrue(len(self.logger.buffer) == 0)

    async def test_capturing(self):
        # When we start capturing, sys.stdout becomes the wrapper pointing to logger.original_stdout (StringIO)
        self.logger.start_capturing()
        
        # Print to stdout/stderr (this goes to wrapper -> StringIO)
        print("stdout output")
        print("stderr output", file=sys.stderr)
        
        # Since _StreamWrapper calls _add_to_buffer immediately
        # Now it should have [TERMINAL] label
        # We need to check if the specific string exists in the buffer but with the label
        buffer_content = "".join(self.logger.buffer)
        self.assertIn("[TERMINAL] stdout output", buffer_content)
        self.assertIn("[ERROR] stderr output", buffer_content)
        
        self.logger.stop_capturing()
        
        # Verify streams restored to the logger's original_stdout (which is our StringIO)
        # But for the test process sake, we want to restore real stdout in tearDown
        self.assertEqual(sys.stdout, self.logger.original_stdout)

if __name__ == '__main__':
    # Run async tests
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    test = TestTelegramLogger()
    
    try:
        test.setUp()
        loop.run_until_complete(test.test_flush())
        test.tearDown()
        
        test.setUp()
        loop.run_until_complete(test.test_capturing())
        test.tearDown()
        
        # Run sync test
        test.setUp()
        test.test_buffer_add()
        test.tearDown()
        
        print("✅ All tests passed!")
    except Exception as e:
        # Emergency restore if something crashes
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
