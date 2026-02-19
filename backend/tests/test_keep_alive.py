import sys
import os
import pytest
from fastapi.testclient import TestClient

# Add parent directory to path to import main
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

client = TestClient(app)

def test_keep_alive_root():
    """Test HEAD request to root"""
    response = client.head("/")
    assert response.status_code == 200
    # Create manual HEAD call if needed to verify header specifically?
    # TestClient handles it.

def test_keep_alive_health():
    """Test HEAD request to /health"""
    response = client.head("/health")
    assert response.status_code == 200

def test_get_still_works():
    """Ensure GET still works as expected"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

if __name__ == "__main__":
    try:
        test_keep_alive_root()
        print("test_keep_alive_root passed")
        test_keep_alive_health()
        print("test_keep_alive_health passed")
        test_get_still_works()
        print("test_get_still_works passed")
        print("All tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")
        exit(1)
