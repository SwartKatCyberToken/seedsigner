# PGP Integration Testing Guide

This guide explains how to test the PGP integration functionality on your PC without requiring SeedSigner hardware.

## Quick Start

### 1. Run the Comprehensive Test Suite

```bash
# From the SeedSigner directory
./test_pgp_bash.sh
```

This will run all tests and provide a comprehensive report.

### 2. Run Individual Python Test

```bash
# From the SeedSigner directory
python test_pgp.py
```

## Test Scripts

### `test_pgp_bash.sh` - Comprehensive Bash Test Suite

**Features:**
- ✅ Environment validation (Python version, dependencies)
- ✅ Module import testing
- ✅ PGP key generation testing
- ✅ Message signing testing
- ✅ QR code export testing
- ✅ Deterministic key generation testing
- ✅ BIP-85 integration testing
- ✅ Colored output and detailed reporting
- ✅ Automatic dependency checking

**Usage:**
```bash
# Run all tests
./test_pgp_bash.sh

# Run with verbose output
./test_pgp_bash.sh --verbose

# Show help
./test_pgp_bash.sh --help
```

### `test_pgp.py` - Simple Python Test Script

**Features:**
- ✅ Basic functionality testing
- ✅ Import verification
- ✅ Key generation and signing tests

**Usage:**
```bash
python test_pgp.py
```

## What Gets Tested

### Core PGP Functionality
1. **Key Generation** - Ed25519 PGP keys from BIP-39 seed phrases
2. **BIP-85 Integration** - Deterministic child seed derivation
3. **Message Signing** - PGP-compliant signature generation
4. **QR Code Export** - JSON formatting for air-gapped transfer

### Technical Validation
1. **Module Imports** - All PGP components load correctly
2. **Dependencies** - Required packages are available
3. **Deterministic Behavior** - Same seed always produces same keys
4. **Key Indexing** - Different indices produce different keys

## Expected Test Output

When all tests pass, you should see:

```
🧪 SeedSigner PGP Integration Test Suite
==================================================
This script tests PGP functionality that can be verified on PC
without requiring SeedSigner hardware.

🐍 Checking Python Environment
ℹ INFO: Python version: 3.9.7
✓ PASS: Python version 3.7+ detected

📦 Checking Dependencies
✓ PASS: embit is installed
✓ PASS: Pillow is installed
✓ PASS: pyzbar is installed
✓ PASS: qrcode is installed
✓ PASS: urtypes is installed
✓ PASS: nacl is installed

📚 Testing Module Imports
✓ PASS: Seed Model imports successfully
✓ PASS: PGP Manager imports successfully
✓ PASS: QR Types imports successfully
✓ PASS: PGP QR Encoder imports successfully
✓ PASS: PGP QR Decoder imports successfully

🔑 Testing PGP Key Generation
✓ PASS: PGP key generation works correctly

✍️ Testing Message Signing
✓ PASS: Message signing works correctly

📱 Testing QR Code Export
✓ PASS: QR code export works correctly

🔄 Testing Deterministic Key Generation
✓ PASS: Deterministic key generation works correctly

🌱 Testing BIP-85 Integration
✓ PASS: BIP-85 integration works correctly

📊 Test Summary
Tests Passed: 11
Tests Failed: 0

🎉 All tests passed! PGP integration is working correctly.

Next steps:
1. Build and flash SeedSigner SD card image
2. Load a seed phrase in SeedSigner
3. Navigate to Tools → PGP Tools
4. Test 'View PGP Keys' and 'Sign Message' functionality
```

## Troubleshooting

### Common Issues

1. **Permission Denied**
   ```bash
   chmod +x test_pgp_bash.sh
   ```

2. **Missing Dependencies**
   ```bash
   pip3 install -r requirements.txt
   ```

3. **Wrong Directory**
   Make sure you're running from the SeedSigner directory (where `requirements.txt` and `src/` are located)

4. **Python Version**
   Python 3.7+ is required. Check with:
   ```bash
   python3 --version
   ```

### Dependency Installation

If you need to install dependencies manually:

```bash
pip3 install PyNaCl==1.5.0
pip3 install embit==0.8.0
pip3 install qrcode==7.3.1
pip3 install Pillow==10.0.1
pip3 install urtypes==1.0.1
```

## What You Can't Test on PC

❌ **Camera Scanning** - Requires Pi Camera hardware  
❌ **Display Rendering** - Requires Pi display hardware  
❌ **Button Input** - Requires Pi GPIO buttons  
❌ **Full UI Flow** - Requires complete SeedSigner environment  

## Next Steps After Testing

Once all tests pass on your PC:

1. **Build SeedSigner Image** - Follow the official build instructions
2. **Flash SD Card** - Write the image to your SD card
3. **Test Hardware Integration** - Verify PGP tools work with actual hardware
4. **Test End-to-End Workflow** - Try the complete message signing flow

## Test Data

The test scripts use a standard test seed phrase:
```
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
```

This is a known test seed that produces predictable results for validation purposes.

## Contributing

If you find issues or want to add more tests:

1. **Report Issues** - Create an issue with test output and error details
2. **Add Tests** - Extend the test scripts with additional validation
3. **Improve Coverage** - Add tests for edge cases and error conditions

## Security Note

The test seed phrase used in these tests is publicly known and should **NEVER** be used for actual cryptocurrency or PGP operations. It's only for testing the implementation.
