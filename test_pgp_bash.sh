#!/bin/bash

# PGP Integration Test Script for SeedSigner
# This script tests PGP functionality that can be verified on PC without hardware

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Function to print colored output
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
            echo -e "${BLUE}ℹ INFO${NC}: $message
            ;;
        "WARN")
            echo -e "${YELLOW}⚠ WARN${NC}: $message
            ;;
    esac
}

# Function to run a test
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    echo -e "\n${BLUE}🧪 Testing: $test_name${NC}"
    echo "Command: $test_command"
    
    if eval "$test_command" > /tmp/pgp_test_output.log 2>&1; then
        print_status "PASS" "$test_name"
        if [ "$VERBOSE" = "true" ]; then
            echo "Output:"
            cat /tmp/pgp_test_output.log
        fi
    else
        print_status "FAIL" "$test_name"
        echo "Error output:"
        cat /tmp/pgp_test_output.log
        return 1
    fi
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check Python version
check_python_version() {
    echo -e "\n${BLUE}🐍 Checking Python Environment${NC}"
    
    if ! command_exists python3; then
        print_status "FAIL" "Python 3 is not installed"
        return 1
    fi
    
    local python_version=$(python3 --version 2>&1 | awk '{print $2}')
    print_status "INFO" "Python version: $python_version"
    
    # Check if version is 3.7 or higher
    local major=$(echo $python_version | cut -d. -f1)
    local minor=$(echo $python_version | cut -d. -f2)
    
    if [ "$major" -eq 3 ] && [ "$minor" -ge 7 ]; then
        print_status "PASS" "Python version 3.7+ detected"
    else
        print_status "WARN" "Python version $python_version detected. 3.7+ recommended."
    fi
}

# Function to check and install dependencies
check_dependencies() {
    echo -e "\n${BLUE}📦 Checking Dependencies${NC}"
    
    local missing_deps=()
    
    # Check required Python packages
    local required_packages=("embit" "Pillow" "pyzbar" "qrcode" "urtypes" "nacl")
    
    for package in "${required_packages[@]}"; do
        if python3 -c "import $package" 2>/dev/null; then
            print_status "PASS" "$package is installed"
        else
            print_status "FAIL" "$package is missing"
            missing_deps+=("$package")
        fi
    done
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo -e "\n${YELLOW}⚠ Missing dependencies detected.${NC}"
        echo "Missing: ${missing_deps[*]}"
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
}

# Function to test basic imports
test_imports() {
    echo -e "\n${BLUE}📚 Testing Module Imports${NC}"
    
    local import_tests=(
        "Seed Model:from seedsigner.models.seed import Seed"
        "PGP Manager:from seedsigner.models.pgp_manager import PGPKeyManager"
        "QR Types:from seedsigner.models.qr_type import QRType"
        "PGP QR Encoder:from seedsigner.models.encode_qr import PGPSignedMessageQrEncoder"
        "PGP QR Decoder:from seedsigner.models.decode_qr import PGPQrDecoder"
    )
    
    for test in "${import_tests[@]}"; do
        local test_name="${test%:*}"
        local import_statement="${test#*:}"
        
        if python3 -c "$import_statement" 2>/dev/null; then
            print_status "PASS" "$test_name imports successfully"
        else
            print_status "FAIL" "$test_name import failed"
        fi
    done
}

# Function to test PGP key generation
test_key_generation() {
    echo -e "\n${BLUE}🔑 Testing PGP Key Generation${NC}"
    
    local test_script='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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
print(f"Created: {key.created_at}")

# Verify key properties
assert key.key_id == "ed25519_0", f"Expected key_id 'ed25519_0', got '{key.key_id}'"
assert key.key_type == "ed25519", f"Expected key_type 'ed25519', got '{key.key_type}'"
assert len(key.fingerprint) > 0, "Fingerprint should not be empty"
assert key.created_at > 0, "Created timestamp should be positive"

print("✓ Key generation test passed")
'
    
    if echo "$test_script" | python3; then
        print_status "PASS" "PGP key generation works correctly"
    else
        print_status "FAIL" "PGP key generation failed"
        return 1
    fi
}

# Function to test message signing
test_message_signing() {
    echo -e "\n${BLUE}✍️ Testing Message Signing${NC}"
    
    local test_script='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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
print(f"Signature starts with: {signature[:50]}...")

# Verify signature properties
assert len(signature) > 100, "Signature should be substantial length"
assert "-----BEGIN PGP SIGNATURE-----" in signature, "Signature should contain PGP header"
assert "-----END PGP SIGNATURE-----" in signature, "Signature should contain PGP footer"

print("✓ Message signing test passed")
'
    
    if echo "$test_script" | python3; then
        print_status "PASS" "Message signing works correctly"
    else
        print_status "FAIL" "Message signing failed"
        return 1
    fi
}

# Function to test QR code export
test_qr_export() {
    echo -e "\n${BLUE}📱 Testing QR Code Export${NC}"
    
    local test_script='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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
print(f"QR data preview: {qr_data[:100]}...")

# Verify QR data properties
import json
try:
    qr_json = json.loads(qr_data)
    assert qr_json["type"] == "pgp_signed_message", "QR data should have correct type"
    assert qr_json["message"] == test_message, "QR data should contain original message"
    assert qr_json["signature"] == signature, "QR data should contain signature"
    assert "key_fingerprint" in qr_json, "QR data should contain key fingerprint"
    print("✓ QR data JSON validation passed")
except json.JSONDecodeError as e:
    print(f"✗ QR data JSON validation failed: {e}")
    return 1

print("✓ QR code export test passed")
'
    
    if echo "$test_script" | python3; then
        print_status "PASS" "QR code export works correctly"
    else
        print_status "FAIL" "QR code export failed"
        return 1
    fi
}

# Function to test deterministic key generation
test_deterministic_keys() {
    echo -e "\n${BLUE}🔄 Testing Deterministic Key Generation${NC}"
    
    local test_script='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

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

print(f"Key 1 fingerprint: {key1.fingerprint}")
print(f"Key 2 fingerprint: {key2.fingerprint}")

# Verify keys are identical
assert key1.fingerprint == key2.fingerprint, "Keys should be identical for same seed"
assert key1.key_id == key2.key_id, "Key IDs should be identical"
assert key1.public_key == key2.public_key, "Public keys should be identical"

print("✓ Deterministic key generation test passed")
'
    
    if echo "$test_script" | python3; then
        print_status "PASS" "Deterministic key generation works correctly"
    else
        print_status "FAIL" "Deterministic key generation failed"
        return 1
    fi
}

# Function to test BIP-85 integration
test_bip85_integration() {
    echo -e "\n${BLUE}🌱 Testing BIP-85 Integration${NC}"
    
    local test_script='
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from seedsigner.models.seed import Seed
from seedsigner.models.pgp_manager import PGPKeyManager

# Test seed phrase
test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
seed = Seed(mnemonic=test_mnemonic.split())

# Generate PGP key
pgp_manager = PGPKeyManager(seed)
key = pgp_manager.get_or_generate_key("ed25519", 0)

# Test different key indices
key0 = pgp_manager.get_or_generate_key("ed25519", 0)
key1 = pgp_manager.get_or_generate_key("ed25519", 1)
key2 = pgp_manager.get_or_generate_key("ed25519", 2)

print(f"Key 0 fingerprint: {key0.fingerprint}")
print(f"Key 1 fingerprint: {key1.fingerprint}")
print(f"Key 2 fingerprint: {key2.fingerprint}")

# Verify keys are different
assert key0.fingerprint != key1.fingerprint, "Different indices should produce different keys"
assert key1.fingerprint != key2.fingerprint, "Different indices should produce different keys"
assert key0.fingerprint != key2.fingerprint, "Different indices should produce different keys"

print("✓ BIP-85 integration test passed")
'
    
    if echo "$test_script" | python3; then
        print_status "PASS" "BIP-85 integration works correctly"
    else
        print_status "FAIL" "BIP-85 integration failed"
        return 1
    fi
}

# Function to run all tests
run_all_tests() {
    echo -e "\n${BLUE}🚀 Running All PGP Tests${NC}"
    
    # Basic environment tests
    check_python_version
    check_dependencies
    
    # Core functionality tests
    test_imports
    test_key_generation
    test_message_signing
    test_qr_export
    test_deterministic_keys
    test_bip85_integration
    
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
        return 0
    else
        echo -e "\n${RED}❌ Some tests failed. Please check the error messages above.${NC}"
        return 1
    fi
}

# Main script
main() {
    echo -e "${BLUE}🧪 SeedSigner PGP Integration Test Suite${NC}"
    echo "=================================================="
    echo "This script tests PGP functionality that can be verified on PC"
    echo "without requiring SeedSigner hardware."
    echo ""
    
    # Parse command line arguments
    VERBOSE=false
    while [[ $# -gt 0 ]]; do
        case $1 in
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  -v, --verbose    Show detailed test output"
                echo "  -h, --help       Show this help message"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Use -h or --help for usage information"
                exit 1
                ;;
        esac
    done
    
    # Check if we're in the right directory
    if [ ! -f "requirements.txt" ] || [ ! -d "src" ]; then
        echo -e "${RED}❌ Error: Please run this script from the SeedSigner directory${NC}"
        echo "Current directory: $(pwd)"
        echo "Expected files: requirements.txt, src/"
        exit 1
    fi
    
    # Run all tests
    run_all_tests
}

# Run main function
main "$@"
