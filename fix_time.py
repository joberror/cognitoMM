#!/usr/bin/env python3
"""
Time Synchronization Helper for MovieBot

This script helps fix time synchronization issues that cause
"BadMsgNotification: msg_id is too high" errors with Telegram.
"""

import subprocess
import sys
import time
from datetime import datetime
import socket
import struct

def get_ntp_time():
    """Get time from NTP server"""
    try:
        # NTP server
        ntp_server = "pool.ntp.org"

        # Create socket
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(10)

        # NTP packet format
        data = b'\x1b' + 47 * b'\0'

        # Send request
        client.sendto(data, (ntp_server, 123))
        data, address = client.recvfrom(1024)
        client.close()

        # Extract timestamp (bytes 40-44)
        timestamp = struct.unpack("!I", data[40:44])[0]

        # Convert to datetime (NTP epoch is 1900-01-01)
        ntp_time = datetime.utcfromtimestamp(timestamp - 2208988800)
        return ntp_time
    except Exception as e:
        print(f"⚠️ Error getting NTP time: {e}")
        return None

def check_system_time():
    """Check current system time and compare with NTP time"""
    print("🕐 Checking system time...")

    # Get system time
    system_time = datetime.utcnow()
    print(f"📅 System time (UTC): {system_time}")

    # Get NTP time
    ntp_time = get_ntp_time()
    if ntp_time:
        print(f"🌐 NTP time (UTC): {ntp_time}")

        # Calculate difference
        diff = abs((system_time - ntp_time).total_seconds())
        print(f"⏰ Time difference: {diff:.1f} seconds")

        if diff > 300:  # More than 5 minutes difference
            print("❌ System time is significantly off!")
            return False
        else:
            print("✅ System time is reasonably accurate")
            return True
    else:
        print("⚠️ Could not fetch NTP time")
        return None

def sync_time():
    """Attempt to synchronize system time"""
    print("\n🔄 Attempting to synchronize time...")
    
    commands = [
        # Try ntpdate first
        ["sudo", "ntpdate", "-s", "time.nist.gov"],
        ["sudo", "ntpdate", "-s", "pool.ntp.org"],
        # Try timedatectl
        ["sudo", "timedatectl", "set-ntp", "true"],
        # Try systemd-timesyncd
        ["sudo", "systemctl", "restart", "systemd-timesyncd"],
    ]
    
    for cmd in commands:
        try:
            print(f"🔧 Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"✅ Success: {' '.join(cmd)}")
                time.sleep(2)  # Wait a bit for sync
                break
            else:
                print(f"⚠️ Failed: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print(f"⏰ Timeout: {' '.join(cmd)}")
        except FileNotFoundError:
            print(f"❌ Command not found: {cmd[0]}")
        except Exception as e:
            print(f"❌ Error: {e}")

def main():
    print("🎬 MovieBot Time Synchronization Helper")
    print("=" * 50)
    
    # Check if running as root for time sync
    if sys.platform.startswith('linux'):
        import os
        if os.geteuid() != 0:
            print("⚠️ Note: Time synchronization requires sudo privileges")
    
    # Check current time
    is_accurate = check_system_time()
    
    if is_accurate is False:
        print("\n🔧 System time needs synchronization")
        sync_time()
        
        # Check again after sync
        print("\n🔍 Checking time after synchronization...")
        check_system_time()
    elif is_accurate is True:
        print("\n✅ System time appears to be accurate")
        print("💡 If you're still getting time errors, try:")
        print("   1. Restart the MovieBot application")
        print("   2. Clear Pyrogram session files")
        print("   3. Check network connectivity")
    
    print("\n🚀 You can now try running the MovieBot again")

if __name__ == "__main__":
    main()
