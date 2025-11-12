#!/usr/bin/env python3
"""
Fixed comprehensive test script for auto-delete functionality in main.py
Tests syntax, imports, function logic, integration, edge cases, and performance
"""

import sys
import os
import asyncio
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add current directory to path to import main modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class TestResults:
    """Store test results for reporting"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.warnings = []
        self.performance_data = {}
        
    def add_pass(self, test_name):
        self.passed += 1
        logger.info(f"✅ PASSED: {test_name}")
        
    def add_fail(self, test_name, error):
        self.failed += 1
        error_msg = f"❌ FAILED: {test_name} - {error}"
        self.errors.append(error_msg)
        logger.error(error_msg)
        
    def add_warning(self, warning):
        self.warnings.append(f"⚠️ WARNING: {warning}")
        logger.warning(warning)
        
    def add_performance(self, test_name, data):
        self.performance_data[test_name] = data

# Initialize test results
results = TestResults()

async def test_syntax_and_imports():
    """Test 1: Check if all imports are correct and no syntax errors exist"""
    logger.info("Running Test 1: Syntax and Import Verification")
    
    try:
        # Test importing main module
        import main
        
        results.add_pass("Main module import successful")
        
        # Check if all required imports are present
        required_imports = [
            'os', 're', 'asyncio', 'sys', 'threading', 'time', 
            'uuid', 'logging', 'datetime', 'dotenv', 'fuzzywuzzy',
            'motor', 'hydrogram'
        ]
        
        for imp in required_imports:
            if imp in sys.modules or hasattr(main, imp):
                results.add_pass(f"Import '{imp}' available")
            else:
                results.add_fail(f"Import '{imp}' missing", "Not found in sys.modules or main module")
        
        # Check if global variables are properly defined
        required_globals = ['file_deletions', 'bulk_downloads']
        for global_var in required_globals:
            if hasattr(main, global_var):
                results.add_pass(f"Global variable '{global_var}' defined")
            else:
                results.add_fail(f"Global variable '{global_var}' missing", "Not found in main module")
                
        return True
        
    except SyntaxError as e:
        results.add_fail("Syntax error in main.py", str(e))
        return False
    except ImportError as e:
        results.add_fail("Import error in main.py", str(e))
        return False
    except Exception as e:
        results.add_fail("Unexpected error during import test", str(e))
        return False

async def test_file_tracking_system():
    """Test 2: Test track_file_for_deletion function with sample data"""
    logger.info("Running Test 2: File Tracking System")
    
    try:
        import main
        
        # Mock client for testing
        main.client = Mock()
        
        # Test 1: Basic tracking with default deletion time
        test_user_id = 12345
        test_message_id = 67890
        
        # Clear any existing data
        main.file_deletions.clear()
        
        # Run the tracking function
        file_id = await main.track_file_for_deletion(test_user_id, test_message_id)
        
        # Verify tracking data
        assert file_id in main.file_deletions, "File ID not found in tracking dictionary"
        tracking_data = main.file_deletions[file_id]
        
        assert tracking_data['user_id'] == test_user_id, "User ID mismatch"
        assert tracking_data['message_id'] == test_message_id, "Message ID mismatch"
        assert tracking_data['notified'] == False, "Notified flag should be False initially"
        assert 'delete_at' in tracking_data, "delete_at timestamp missing"
        assert 'sent_at' in tracking_data, "sent_at timestamp missing"
        
        # Check if delete_at is approximately 15 minutes from now
        expected_delete_time = datetime.now(timezone.utc) + timedelta(minutes=15)
        actual_delete_time = tracking_data['delete_at']
        time_diff = abs((actual_delete_time - expected_delete_time).total_seconds())
        assert time_diff < 60, f"Delete time mismatch: {time_diff} seconds difference"
        
        results.add_pass("Basic file tracking with default time")
        
        # Test 2: Custom deletion time
        custom_delete_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        file_id2 = await main.track_file_for_deletion(test_user_id, test_message_id + 1, custom_delete_time)
        
        tracking_data2 = main.file_deletions[file_id2]
        assert tracking_data2['delete_at'] == custom_delete_time, "Custom delete time not set correctly"
        
        results.add_pass("File tracking with custom deletion time")
        
        # Test 3: Verify unique file IDs
        assert file_id != file_id2, "File IDs should be unique"
        assert len(main.file_deletions) == 2, "Should have 2 tracked files"
        
        results.add_pass("Unique file ID generation")
        
        return True
        
    except Exception as e:
        results.add_fail("File tracking system test", str(e))
        return False

async def test_background_task_system():
    """Test 3: Verify check_files_for_deletion logic for timing and notifications"""
    logger.info("Running Test 3: Background Task System")
    
    try:
        import main
        
        # Mock client and file_deletions
        main.client = AsyncMock()
        main.file_deletions = {}
        
        # Test 1: No files to process
        await main.check_files_for_deletion()
        results.add_pass("Empty file deletions handling")
        
        # Test 2: File not yet due for warning or deletion
        test_user_id = 12345
        test_message_id = 67890
        future_time = datetime.now(timezone.utc) + timedelta(minutes=20)
        
        file_id = await main.track_file_for_deletion(test_user_id, test_message_id, future_time)
        
        # Run check - should not send any notifications
        await main.check_files_for_deletion()
        
        # Verify no client calls were made
        assert main.client.send_message.call_count == 0, "No notifications should be sent for future files"
        assert main.client.delete_messages.call_count == 0, "No deletions should occur for future files"
        
        results.add_pass("Future file handling (no actions)")
        
        # Test 3: File due for 5-minute warning
        warning_time = datetime.now(timezone.utc) + timedelta(minutes=4, seconds=50)  # Just before 5-minute mark
        file_id2 = await main.track_file_for_deletion(test_user_id, test_message_id + 1, warning_time)
        
        # Reset mock call counts
        main.client.reset_mock()
        
        # Run check - should send warning
        await main.check_files_for_deletion()
        
        # Verify warning was sent
        assert main.client.send_message.call_count == 1, "Warning message should be sent"
        assert main.client.delete_messages.call_count == 0, "No deletion should occur yet"
        
        # Check warning message content
        call_args = main.client.send_message.call_args
        assert call_args[0][0] == test_user_id, "Warning sent to wrong user"
        assert "5-Minute Warning" in call_args[0][1], "Warning message content incorrect"
        
        results.add_pass("5-minute warning notification")
        
        # Test 4: File due for deletion
        past_time = datetime.now(timezone.utc) - timedelta(minutes=1)  # Past deletion time
        file_id3 = await main.track_file_for_deletion(test_user_id, test_message_id + 2, past_time)
        
        # Reset mock call counts
        main.client.reset_mock()
        
        # Run check - should delete and send notification
        await main.check_files_for_deletion()
        
        # Verify deletion and notification
        assert main.client.delete_messages.call_count == 1, "File should be deleted"
        assert main.client.send_message.call_count == 1, "Deletion notification should be sent"
        
        # Check deletion call
        delete_args = main.client.delete_messages.call_args
        assert delete_args[0][0] == test_user_id, "Deletion from wrong user"
        assert delete_args[0][1] == test_message_id + 2, "Wrong message ID deleted"
        
        # Check notification call
        notify_args = main.client.send_message.call_args
        assert notify_args[0][0] == test_user_id, "Notification sent to wrong user"
        assert "Auto-Deleted" in notify_args[0][1], "Deletion notification content incorrect"
        
        results.add_pass("File deletion and notification")
        
        # Test 5: Verify file removed from tracking after deletion
        assert file_id3 not in main.file_deletions, "File should be removed from tracking after deletion"
        
        results.add_pass("File removal from tracking after deletion")
        
        return True
        
    except Exception as e:
        results.add_fail("Background task system test", str(e))
        return False

async def test_cleanup_functionality():
    """Test 4: Test cleanup_expired_file_deletions function"""
    logger.info("Running Test 4: Cleanup Functionality")
    
    try:
        import main
        
        # Setup test data
        main.file_deletions = {}
        test_user_id = 12345
        test_message_id = 67890
        
        # Test 1: Recent file (should not be cleaned up)
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)  # 30 minutes ago
        file_id1 = await main.track_file_for_deletion(test_user_id, test_message_id, recent_time)
        
        # Manually set delete_at to be more than 1 hour ago for cleanup test
        main.file_deletions[file_id1]['delete_at'] = datetime.now(timezone.utc) - timedelta(minutes=90)
        
        # Test 2: Old file (should be cleaned up)
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)  # 2 hours ago
        file_id2 = await main.track_file_for_deletion(test_user_id, test_message_id + 1, old_time)
        
        # Run cleanup
        await main.cleanup_expired_file_deletions()
        
        # Verify results
        assert file_id1 in main.file_deletions, "Recent file should not be cleaned up"
        assert file_id2 not in main.file_deletions, "Old file should be cleaned up"
        
        results.add_pass("Cleanup of expired file deletions")
        
        return True
        
    except Exception as e:
        results.add_fail("Cleanup functionality test", str(e))
        return False

async def test_error_handling():
    """Test 5: Test error handling for various failure scenarios"""
    logger.info("Running Test 5: Error Handling")
    
    try:
        import main
        
        # Mock client to raise exceptions
        main.client = AsyncMock()
        
        # Test 1: Warning message sending failure
        main.client.send_message.side_effect = Exception("Failed to send warning")
        
        warning_time = datetime.now(timezone.utc) + timedelta(minutes=4, seconds=50)
        file_id = await main.track_file_for_deletion(12345, 67890, warning_time)
        
        # Run check - should handle warning failure gracefully
        await main.check_files_for_deletion()
        
        # Verify file is still tracked despite warning failure
        assert file_id in main.file_deletions, "File should remain tracked after warning failure"
        assert main.file_deletions[file_id]['notified'] == True, "Notified flag should be set despite failure"
        
        results.add_pass("Warning message failure handling")
        
        # Test 2: Deletion failure
        main.client.reset_mock()
        main.client.delete_messages.side_effect = Exception("Failed to delete message")
        main.client.send_message.side_effect = None  # Reset to normal
        
        past_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        file_id2 = await main.track_file_for_deletion(12345, 67891, past_time)
        
        # Run check - should handle deletion failure gracefully
        await main.check_files_for_deletion()
        
        # Verify file is removed from tracking despite deletion failure
        assert file_id2 not in main.file_deletions, "File should be removed from tracking even if deletion fails"
        
        results.add_pass("Deletion failure handling")
        
        # Test 3: Notification failure after deletion
        main.client.reset_mock()
        main.client.delete_messages.side_effect = None  # Reset to normal
        main.client.send_message.side_effect = Exception("Failed to send notification")
        
        past_time2 = datetime.now(timezone.utc) - timedelta(minutes=1)
        file_id3 = await main.track_file_for_deletion(12345, 67892, past_time2)
        
        # Run check - should handle notification failure gracefully
        await main.check_files_for_deletion()
        
        # Verify deletion occurred despite notification failure
        assert main.client.delete_messages.call_count == 1, "Deletion should still occur"
        assert file_id3 not in main.file_deletions, "File should be removed from tracking"
        
        results.add_pass("Notification failure handling")
        
        return True
        
    except Exception as e:
        results.add_fail("Error handling test", str(e))
        return False

async def test_integration_points():
    """Test 6: Verify callback handler modifications don't break existing functionality"""
    logger.info("Running Test 6: Integration Points")
    
    try:
        import main
        from hydrogram.types import CallbackQuery, Message
        
        # Mock client and related objects
        main.client = AsyncMock()
        
        # Test 1: Single file download callback
        callback_query = Mock()
        callback_query.data = "get_file:123456:789012"
        callback_query.from_user.id = 12345
        callback_query.answer = AsyncMock()
        
        # Mock the get_messages response
        mock_message = Mock()
        mock_message.video = Mock()
        mock_message.video.file_id = "test_file_id"
        mock_message.caption = "Test video"
        
        main.client.get_messages.return_value = mock_message
        main.client.send_cached_media.return_value = Mock(id=999999)
        
        # Mock the track_file_for_deletion function
        with patch.object(main, 'track_file_for_deletion', AsyncMock()) as mock_track:
            # Run callback handler
            await main.callback_handler(main.client, callback_query)
            
            # Verify file tracking was called
            mock_track.assert_called_once_with(
                user_id=12345,
                message_id=999999
            )
            
            results.add_pass("Single file download integration")
        
        # Test 2: Bulk download callback
        main.client.reset_mock()
        callback_query.data = "bulk:test_bulk_id"
        
        # Setup bulk download data
        main.bulk_downloads = {
            'test_bulk_id': {
                'files': [
                    {'channel_id': 123456, 'message_id': 789012},
                    {'channel_id': 123456, 'message_id': 789013}
                ],
                'created_at': datetime.now(timezone.utc),
                'user_id': 12345
            }
        }
        
        # Mock messages
        mock_messages = [
            Mock(video=Mock(file_id="file1"), caption="Video 1"),
            Mock(video=Mock(file_id="file2"), caption="Video 2")
        ]
        main.client.get_messages.side_effect = mock_messages
        main.client.send_cached_media.side_effect = [Mock(id=888888), Mock(id=888889)]
        
        with patch.object(main, 'track_file_for_deletion', AsyncMock()) as mock_track:
            # Run callback handler
            await main.callback_handler(main.client, callback_query)
            
            # Verify file tracking was called for each file
            assert mock_track.call_count == 2, "Should track both files in bulk download"
            mock_track.assert_any_call(user_id=12345, message_id=888888)
            mock_track.assert_any_call(user_id=12345, message_id=888889)
            
            results.add_pass("Bulk download integration")
        
        return True
        
    except Exception as e:
        results.add_fail("Integration points test", str(e))
        return False

async def test_performance_considerations():
    """Test 7: Test performance and scalability"""
    logger.info("Running Test 7: Performance Considerations")
    
    try:
        import main
        
        # Test 1: Memory usage with many tracked files
        main.file_deletions = {}
        start_time = time.time()
        
        # Track 1000 files
        for i in range(1000):
            await main.track_file_for_deletion(i, i*1000)
        
        track_time = time.time() - start_time
        results.add_performance("Track 1000 files", {
            'time_seconds': track_time,
            'files_tracked': 1000,
            'time_per_file': track_time / 1000
        })
        
        # Test 2: Check performance with many files
        start_time = time.time()
        await main.check_files_for_deletion()
        check_time = time.time() - start_time
        
        results.add_performance("Check 1000 files", {
            'time_seconds': check_time,
            'files_checked': 1000,
            'time_per_file': check_time / 1000
        })
        
        # Test 3: Cleanup performance
        start_time = time.time()
        await main.cleanup_expired_file_deletions()
        cleanup_time = time.time() - start_time
        
        results.add_performance("Cleanup 1000 files", {
            'time_seconds': cleanup_time,
            'files_cleaned': 1000,
            'time_per_file': cleanup_time / 1000
        })
        
        # Performance assertions
        assert track_time < 1.0, f"Tracking too slow: {track_time}s for 1000 files"
        assert check_time < 0.5, f"Checking too slow: {check_time}s for 1000 files"
        assert cleanup_time < 0.1, f"Cleanup too slow: {cleanup_time}s for 1000 files"
        
        results.add_pass("Performance benchmarks")
        
        # Test 4: Memory efficiency
        import sys
        dict_size = sys.getsizeof(main.file_deletions)
        avg_entry_size = dict_size / len(main.file_deletions) if main.file_deletions else 0
        
        results.add_performance("Memory usage", {
            'total_bytes': dict_size,
            'file_count': len(main.file_deletions),
            'bytes_per_file': avg_entry_size
        })
        
        # Warning about memory usage
        if avg_entry_size > 500:  # 500 bytes per file seems reasonable
            results.add_warning(f"High memory usage per file: {avg_entry_size} bytes")
        
        results.add_pass("Memory efficiency analysis")
        
        return True
        
    except Exception as e:
        results.add_fail("Performance considerations test", str(e))
        return False

async def test_edge_cases():
    """Test 8: Test edge cases and unusual scenarios"""
    logger.info("Running Test 8: Edge Cases")
    
    try:
        import main
        
        # Test 1: Empty file_deletions dictionary
        main.file_deletions = {}
        await main.check_files_for_deletion()
        await main.cleanup_expired_file_deletions()
        results.add_pass("Empty dictionary handling")
        
        # Test 2: Invalid user_id or message_id
        main.client = AsyncMock()
        file_id = await main.track_file_for_deletion(0, -1)
        assert file_id in main.file_deletions, "Should handle invalid IDs"
        results.add_pass("Invalid ID handling")
        
        # Test 3: Very large user_id and message_id
        large_id = 2**31 - 1  # Max 32-bit integer
        file_id2 = await main.track_file_for_deletion(large_id, large_id)
        assert file_id2 in main.file_deletions, "Should handle large IDs"
        results.add_pass("Large ID handling")
        
        # Test 4: Immediate deletion (past time)
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        file_id3 = await main.track_file_for_deletion(12345, 67890, past_time)
        
        main.client.reset_mock()
        await main.check_files_for_deletion()
        
        assert main.client.delete_messages.call_count == 1, "Should handle immediate deletion"
        results.add_pass("Immediate deletion handling")
        
        # Test 5: Very far future deletion
        future_time = datetime.now(timezone.utc) + timedelta(days=365)
        file_id4 = await main.track_file_for_deletion(12345, 67891, future_time)
        
        main.client.reset_mock()
        await main.check_files_for_deletion()
        
        assert main.client.send_message.call_count == 0, "Should not send warnings for far future"
        assert main.client.delete_messages.call_count == 0, "Should not delete far future files"
        results.add_pass("Far future deletion handling")
        
        # Test 6: Duplicate tracking (same user_id and message_id)
        file_id5 = await main.track_file_for_deletion(12345, 67892)
        file_id6 = await main.track_file_for_deletion(12345, 67892)
        
        assert file_id5 != file_id6, "Should create unique IDs even for duplicates"
        assert len(main.file_deletions) >= 2, "Should track both entries"
        results.add_pass("Duplicate tracking handling")
        
        return True
        
    except Exception as e:
        results.add_fail("Edge cases test", str(e))
        return False

def generate_test_report():
    """Generate comprehensive test report"""
    logger.info("Generating comprehensive test report")
    
    report = []
    report.append("=" * 80)
    report.append("AUTO-DELETE FUNCTIONALITY TEST REPORT")
    report.append("=" * 80)
    report.append(f"Test Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report.append(f"Total Tests: {results.passed + results.failed}")
    report.append(f"Passed: {results.passed}")
    report.append(f"Failed: {results.failed}")
    report.append(f"Success Rate: {(results.passed / (results.passed + results.failed) * 100):.1f}%" if (results.passed + results.failed) > 0 else "Success Rate: N/A")
    report.append("")
    
    # Test Results Summary
    report.append("TEST RESULTS SUMMARY:")
    report.append("-" * 40)
    if results.errors:
        report.append("\nFAILED TESTS:")
        for error in results.errors:
            report.append(f"  {error}")
    
    if results.warnings:
        report.append("\nWARNINGS:")
        for warning in results.warnings:
            report.append(f"  {warning}")
    
    # Performance Data
    if results.performance_data:
        report.append("\nPERFORMANCE DATA:")
        report.append("-" * 40)
        for test_name, data in results.performance_data.items():
            report.append(f"\n{test_name}:")
            for key, value in data.items():
                if isinstance(value, float):
                    report.append(f"  {key}: {value:.4f}")
                else:
                    report.append(f"  {key}: {value}")
    
    # Issues and Recommendations
    report.append("\nISSUES IDENTIFIED:")
    report.append("-" * 40)
    
    issues = [
        "1. MEMORY LEAK: file_deletions dictionary is in-memory only",
        "   - Bot restart loses all tracking data",
        "   - No persistent storage for scheduled deletions",
        "",
        "2. RACE CONDITION: Global dictionary accessed without locks",
        "   - Multiple async tasks could modify file_deletions simultaneously",
        "   - Potential data corruption in high-concurrency scenarios",
        "",
        "3. SCALABILITY: In-memory tracking won't scale with many users",
        "   - Each tracked file consumes memory",
        "   - No cleanup mechanism for very old failed deletions",
        "",
        "4. ERROR HANDLING: Limited recovery for failed operations",
        "   - Failed deletions are not retried",
        "   - No logging of persistent failures",
        "",
        "5. TIMEZONE HANDLING: Mixed usage of timezone-aware and naive datetime",
        "   - Potential timing issues in different environments",
        "   - Inconsistent datetime comparisons",
    ]
    
    report.extend(issues)
    
    # Recommendations
    report.append("\nRECOMMENDATIONS:")
    report.append("-" * 40)
    
    recommendations = [
        "1. Implement persistent storage (Redis/Database) for file deletions",
        "2. Add asyncio.Lock() for thread-safe access to file_deletions",
        "3. Implement retry mechanism for failed deletions",
        "4. Add comprehensive logging for debugging",
        "5. Use timezone-aware datetime consistently",
        "6. Add configuration options for deletion timing",
        "7. Implement cleanup for very old failed deletion records",
        "8. Add monitoring and alerting for deletion failures",
        "9. Consider implementing a queue system for better scalability",
        "10. Add unit tests with proper mocking for continuous integration",
    ]
    
    report.extend(recommendations)
    
    report.append("\n" + "=" * 80)
    report.append("END OF REPORT")
    report.append("=" * 80)
    
    return "\n".join(report)

async def main_test():
    """Run all tests and generate report"""
    logger.info("Starting comprehensive auto-delete functionality tests")
    
    # Run all tests
    tests = [
        test_syntax_and_imports,
        test_file_tracking_system,
        test_background_task_system,
        test_cleanup_functionality,
        test_error_handling,
        test_integration_points,
        test_performance_considerations,
        test_edge_cases,
    ]
    
    for test_func in tests:
        try:
            await test_func()
        except Exception as e:
            logger.error(f"Test {test_func.__name__} crashed: {e}")
            results.add_fail(test_func.__name__, f"Test crashed: {e}")
    
    # Generate and save report
    report = generate_test_report()
    
    # Save report to file
    with open("auto_delete_test_report.txt", "w") as f:
        f.write(report)
    
    # Print report to console
    print(report)
    
    logger.info("Test completed. Report saved to auto_delete_test_report.txt")
    
    return results.failed == 0

if __name__ == "__main__":
    # Run the tests
    success = asyncio.run(main_test())
    sys.exit(0 if success else 1)
