
import sys
import os

# Mock the CPU worker logic to test difficulty check
def check_difficulty(digest_hex, target_difficulty):
    # This logic mirrors the fix in worker.py
    digest_int = int(digest_hex[:8], 16)
    return digest_int <= target_difficulty

def test_difficulty_check():
    print("Testing difficulty check logic...")
    
    # Test Case 1: Hash meets target
    # Target: 0x0000FFFF (65535)
    # Hash: 00001234... (starts with 00001234 = 4660)
    # 4660 <= 65535 -> Should pass
    target = 0x0000FFFF
    good_hash = "00001234" + "0" * 56
    if check_difficulty(good_hash, target):
        print("PASS: Good hash accepted")
    else:
        print("FAIL: Good hash rejected")

    # Test Case 2: Hash fails target
    # Target: 0x0000FFFF (65535)
    # Hash: 00010000... (starts with 00010000 = 65536)
    # 65536 <= 65535 -> Should fail
    bad_hash = "00010000" + "0" * 56
    if not check_difficulty(bad_hash, target):
        print("PASS: Bad hash rejected")
    else:
        print("FAIL: Bad hash accepted")

    # Test Case 3: Edge case (Equal)
    # Target: 0x0000FFFF
    # Hash: 0000FFFF...
    # Should pass
    equal_hash = "0000FFFF" + "0" * 56
    if check_difficulty(equal_hash, target):
        print("PASS: Equal hash accepted")
    else:
        print("FAIL: Equal hash rejected")

if __name__ == "__main__":
    test_difficulty_check()
