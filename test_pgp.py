#!/usr/bin/env python3
"""
Simple test script for PGP functionality
Run this from the SeedSigner directory to test PGP key generation and signing
"""

import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_pgp_basic():
    """Test basic PGP functionality"""
    try:
        from seedsigner.models.seed import Seed
        from seedsigner.models.pgp_manager import PGPKeyManager
        
        print("✓ Successfully imported PGP modules")
        
        # Create a test seed
        test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        seed = Seed(mnemonic=test_mnemonic.split())
        
        print("✓ Created test seed")
        
        # Create PGP manager
        pgp_manager = PGPKeyManager(seed)
        print("✓ Created PGP manager")
        
        # Generate a key
        key = pgp_manager.get_or_generate_key("ed25519", 0)
        print("✓ Generated Ed25519 PGP key")
        print(f"  Key ID: {key.key_id}")
        print(f"  Fingerprint: {key.fingerprint}")
        print(f"  Type: {key.key_type}")
        
        # Test message signing
        test_message = "Hello, this is a test message!"
        signature = pgp_manager.sign_message(test_message, "ed25519", 0)
        print("✓ Successfully signed test message")
        print(f"  Message: {test_message}")
        print(f"  Signature length: {len(signature)} characters")
        
        # Test QR code export
        qr_data = pgp_manager.export_signed_message_qr_data(test_message, signature, "ed25519", 0)
        print("✓ Successfully exported signed message QR data")
        print(f"  QR data length: {len(qr_data)} characters")
        
        print("\n🎉 All PGP tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ PGP test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_imports():
    """Test that all required modules can be imported"""
    try:
        print("Testing imports...")
        
        # Test core imports
        from seedsigner.models.seed import Seed
        print("✓ Seed model imported")
        
        from seedsigner.models.pgp_manager import PGPKeyManager
        print("✓ PGP manager imported")
        
        from seedsigner.models.qr_type import QRType
        print("✓ QR types imported")
        
        from seedsigner.models.encode_qr import PGPSignedMessageQrEncoder
        print("✓ PGP QR encoder imported")
        
        print("✓ All imports successful")
        return True
        
    except Exception as e:
        print(f"❌ Import test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing PGP Integration for SeedSigner")
    print("=" * 50)
    
    # Test imports first
    if not test_imports():
        print("\n❌ Import tests failed. Please check dependencies.")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    
    # Test PGP functionality
    if test_pgp_basic():
        print("\n✅ PGP integration is working correctly!")
        print("\nNext steps:")
        print("1. Load a seed phrase in SeedSigner")
        print("2. Go to Tools → PGP Tools")
        print("3. Try 'View PGP Keys' and 'Sign Message'")
    else:
        print("\n❌ PGP integration has issues. Please check the error messages above.")
        sys.exit(1)
