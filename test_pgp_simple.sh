#!/bin/bash

# Simple PGP Integration Test Script for SeedSigner
# This script tests PGP functionality that can be verified on PC

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 SeedSigner PGP Integration Test Suite${NC}"
echo "=================================================="
echo "Testing PGP functionality on PC without hardware"
echo ""

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Function to print status
print_status() {
    local status=$1
    local message=$2
    case $status in
        "PASS")
            echo -e "${GREEN}✓ PASS${NC}: $message"
            ((TESTS_PASSED++))
            ;;
        "FAIL")
            echo -e "${RED}✗ FAIL${NC}: $message"
            ((TESTS_FAILED++))
            ;;
        "INFO")
            echo -e "${BLUE}ℹ INFO${NC}: $message"
            ;;
        "WARN")
            echo -e "${YELLOW}⚠ WARN${NC}: $message"
            ;;
    esac
}

# Check Python environment
echo -e "${BLUE}🐍 Checking Python Environment${NC}"
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    print_status "INFO" "Python version: $PYTHON_VERSION"
    
    # Check if version is 3.7 or higher
    MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 7 ]; then
        print_status "PASS" "Python version 3.7+ detected"
    else
        print_status "WARN" "Python version $PYTHON_VERSION detected. 3.7+ recommended."
    fi
else
    print_status "FAIL" "Python 3 is not installed"
    exit 1
fi

# Check dependencies
echo -e "\n${BLUE}📦 Checking Dependencies${NC}"
MISSING_DEPS=()

for package in embit Pillow pyzbar qrcode urtypes nacl; do
    if python3 -c "import $package" 2>/dev/null; then
        print_status "PASS" "$package is installed"
    else
        print_status "FAIL" "$package is missing"
        MISSING_DEPS+=("$package")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "\n${YELLOW}⚠ Missing dependencies detected.${NC}"
    echo "Missing: ${MISSING_DEPS[*]}"
    echo -e "\nTo install missing dependencies, run:"
    echo "pip3 install -r requirements.txt"
    
    read -p "Would you like to install missing dependencies now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing dependencies..."
        pip3 install -r requirements.txt
    else
        print_status "WARN" "Continuing without installing dependencies"
    fi
fi

# Test imports
echo -e "\n${BLUE}📚 Testing Module Imports${NC}"
for module in "seedsigner.models.seed:Seed" "seedsigner.models.pgp_manager:PGPKeyManager" "seedsigner.models.qr_type:QRType"; do
    MODULE_NAME="${module%:*}"
    CLASS_NAME="${module#*:}"
    
    if python3 -c "from $MODULE_NAME import $CLASS_NAME" 2>/dev/null; then
        print_status "PASS" "$CLASS_NAME imports successfully"
    else
        print_status "FAIL" "$CLASS_NAME import failed"
    fi
done

# Test PGP key generation
echo -e "\n${BLUE}🔑 Testing PGP Key Generation${NC}"
TEST_SCRIPT='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

try:
    from seedsigner.models.seed import Seed
    from seedsigner.models.pgp_manager import PGPKeyManager
    
    # Test seed phrase
    test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    seed = Seed(mnemonic=test_mnemonic.split())
    
    # Generate PGP key
    pgp_manager = PGPKeyManager(seed)
    key = pgp_manager.get_or_generate_key("ed25519", 0)
    
    print(f"Key ID: {key.key_id}")
    print(f"Fingerprint: {key.fingerprint}")
    print(f"Type: {key.key_type}")
    
    # Verify key properties
    assert key.key_id == "ed25519_0"
    assert key.key_type == "ed25519"
    assert len(key.fingerprint) > 0
    
    print("✓ Key generation test passed")
    
except Exception as e:
    print(f"✗ Key generation test failed: {e}")
    sys.exit(1)
'

if echo "$TEST_SCRIPT" | python3; then
    print_status "PASS" "PGP key generation works correctly"
else
    print_status "FAIL" "PGP key generation failed"
fi

# Test message signing
echo -e "\n${BLUE}✍️ Testing Message Signing${NC}"
SIGNING_SCRIPT='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

try:
    from seedsigner.models.seed import Seed
    from seedsigner.models.pgp_manager import PGPKeyManager
    
    # Test seed phrase
    test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    seed = Seed(mnemonic=test_mnemonic.split())
    
    # Generate PGP key
    pgp_manager = PGPKeyManager(seed)
    key = pgp_manager.get_or_generate_key("ed25519", 0)
    
    # Test message signing
    test_message = "Hello, this is a test message for PGP signing!"
    signature = pgp_manager.sign_message(test_message, "ed25519", 0)
    
    print(f"Message: {test_message}")
    print(f"Signature length: {len(signature)} characters")
    
    # Verify signature properties
    assert len(signature) > 100
    assert "-----BEGIN PGP SIGNATURE-----" in signature
    assert "-----END PGP SIGNATURE-----" in signature
    
    print("✓ Message signing test passed")
    
except Exception as e:
    print(f"✗ Message signing test failed: {e}")
    sys.exit(1)
'

if echo "$SIGNING_SCRIPT" | python3; then
    print_status "PASS" "Message signing works correctly"
else
    print_status "FAIL" "Message signing failed"
fi

# Test QR code export
echo -e "\n${BLUE}📱 Testing QR Code Export${NC}"
QR_SCRIPT='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

try:
    from seedsigner.models.seed import Seed
    from seedsigner.models.pgp_manager import PGPKeyManager
    
    # Test seed phrase
    test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    seed = Seed(mnemonic=test_mnemonic.split())
    
    # Generate PGP key
    pgp_manager = PGPKeyManager(seed)
    key = pgp_manager.get_or_generate_key("ed25519", 0)
    
    # Test message signing
    test_message = "Hello, this is a test message for PGP signing!"
    signature = pgp_manager.sign_message(test_message, "ed25519", 0)
    
    # Test QR code export
    qr_data = pgp_manager.export_signed_message_qr_data(test_message, signature, "ed25519", 0)
    
    print(f"QR data length: {len(qr_data)} characters")
    
    # Verify QR data properties
    import json
    qr_json = json.loads(qr_data)
    assert qr_json["type"] == "pgp_signed_message"
    assert qr_json["message"] == test_message
    assert qr_json["signature"] == signature
    assert "key_fingerprint" in qr_json
    
    print("✓ QR code export test passed")
    
except Exception as e:
    print(f"✗ QR code export test failed: {e}")
    sys.exit(1)
'

if echo "$QR_SCRIPT" | python3; then
    print_status "PASS" "QR code export works correctly"
else
    print_status "FAIL" "QR code export failed"
fi

# Test deterministic key generation
echo -e "\n${BLUE}🔄 Testing Deterministic Key Generation${NC}"
DET_SCRIPT='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

try:
    from seedsigner.models.seed import Seed
    from seedsigner.models.pgp_manager import PGPKeyManager
    
    # Test seed phrase
    test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    seed = Seed(mnemonic=test_mnemonic.split())
    
    # Generate PGP key twice
    pgp_manager1 = PGPKeyManager(seed)
    key1 = pgp_manager1.get_or_generate_key("ed25519", 0)
    
    pgp_manager2 = PGPKeyManager(seed)
    key2 = pgp_manager2.get_or_generate_key("ed25519", 0)
    
    # Verify keys are identical
    assert key1.fingerprint == key2.fingerprint
    assert key1.key_id == key2.key_id
    assert key1.public_key == key2.public_key
    
    print("✓ Deterministic key generation test passed")
    
except Exception as e:
    print(f"✗ Deterministic key generation test failed: {e}")
    sys.exit(1)
'

if echo "$DET_SCRIPT" | python3; then
    print_status "PASS" "Deterministic key generation works correctly"
else
    print_status "FAIL" "Deterministic key generation failed"
fi

# Summary
echo -e "\n${BLUE}📊 Test Summary${NC}"
echo -e "${GREEN}Tests Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Tests Failed: $TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}🎉 All tests passed! PGP integration is working correctly.${NC}"
    echo -e "\nNext steps:"
    echo "1. Build and flash SeedSigner SD card image"
    echo "2. Load a seed phrase in SeedSigner"
    echo "3. Navigate to Tools → PGP Tools"
    echo "4. Test 'View PGP Keys' and 'Sign Message' functionality"
    exit 0
else
    echo -e "\n${RED}❌ Some tests failed. Please check the error messages above.${NC}"
    exit 1
fi
