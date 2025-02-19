#!/usr/bin/env python3
import os
import sys
import requests
from requests_oauthlib import OAuth1

# -------------------------------------------------------------------
# 1) Your Credentials (from your question):
# -------------------------------------------------------------------
CONSUMER_KEY = "OV8iZ6sFaaEJ59BTQEfV37PEp"
CONSUMER_SECRET = "RkT9X9oVMlB1HSGKSdlcFqKFOm5pyYIvoZjHBdVj46xJ47YlPG"
ACCESS_TOKEN = "1861124464181751808-F2X0ajpXLuuiPJ2XiSuIfCsCm1qaov"
ACCESS_TOKEN_SECRET = "ys7nC8we97As1PZUF4ZXTvivfFfQmiG9YvUrqvTpnoJN1"

# -------------------------------------------------------------------
# 2) Proxy configuration
# -------------------------------------------------------------------
PROXIES = {
    "http":  "http://4dc12c1b7e96f324a06a__cr.us:f9218ab87aa14602@gw.dataimpulse.com:10100",
    "https": "http://4dc12c1b7e96f324a06a__cr.us:f9218ab87aa14602@gw.dataimpulse.com:10100",
}

# -------------------------------------------------------------------
# 3) The local path to your PNG
# -------------------------------------------------------------------
FILE_PATH = "backend/media/12.png"

UPLOAD_ENDPOINT = "https://upload.twitter.com/1.1/media/upload.json"
mime_type = "image/png"
media_category = "tweet_image"   # For PNG/JPG images

oauth = OAuth1(
    client_key=CONSUMER_KEY,
    client_secret=CONSUMER_SECRET,
    resource_owner_key=ACCESS_TOKEN,
    resource_owner_secret=ACCESS_TOKEN_SECRET
)

def check_public_ip():
    """
    Just for debugging. Tries to fetch your public IP via a proxy.
    """
    try:
        r = requests.get("https://api.ipify.org?format=json", proxies=PROXIES, timeout=10)
        r.raise_for_status()
        print(f"[DEBUG] Public IP (via proxy): {r.text}")
    except Exception as e:
        print(f"[DEBUG] Could not determine public IP via proxy: {e}")

def init_upload(file_size):
    """
    Step 1: INIT the upload session.
    """
    data = {
        "command": "INIT",
        "total_bytes": file_size,
        "media_type": mime_type,
        "media_category": media_category,
    }

    resp = requests.post(
        UPLOAD_ENDPOINT,
        data=data,
        auth=oauth,
        proxies=PROXIES
    )
    print("[DEBUG] INIT response code:", resp.status_code)
    print("[DEBUG] INIT response text:", resp.text)

    if resp.status_code not in (200, 201, 202):
        return None

    j = resp.json()
    return j.get("media_id_string")

def append_upload(media_id):
    """
    Step 2: APPEND the file data in a single chunk.
    For images < 5MB, we can do it all in one chunk.
    """
    with open(FILE_PATH, "rb") as f:
        chunk = f.read()

    data = {
        "command": "APPEND",
        "media_id": media_id,
        "segment_index": "0",
    }
    files = {
        # name='media'; tuple -> (filename, file_content, mimetype)
        "media": ("blob", chunk, mime_type),
    }

    resp = requests.post(
        UPLOAD_ENDPOINT,
        data=data,
        files=files,
        auth=oauth,
        proxies=PROXIES
    )
    print("[DEBUG] APPEND response code:", resp.status_code)
    print("[DEBUG] APPEND response text:", resp.text)

    # Usually for success: 204 No Content
    if resp.status_code not in (200, 201, 202, 204):
        return False
    return True

def finalize_upload(media_id):
    """
    Step 3: FINALIZE the upload.
    """
    data = {
        "command": "FINALIZE",
        "media_id": media_id,
    }
    resp = requests.post(
        UPLOAD_ENDPOINT,
        data=data,
        auth=oauth,
        proxies=PROXIES
    )
    print("[DEBUG] FINALIZE response code:", resp.status_code)
    print("[DEBUG] FINALIZE response text:", resp.text)

    if resp.status_code not in (200, 201, 202):
        return None
    return resp.json()

def main():
    # 0) Check that file exists and get size
    if not os.path.exists(FILE_PATH):
        print(f"Error: File '{FILE_PATH}' not found!")
        sys.exit(1)

    file_size = os.path.getsize(FILE_PATH)
    print(f"Uploading {FILE_PATH} (size={file_size} bytes, type={mime_type})")

    # (optional) Check what IP we appear to have via the proxy
    check_public_ip()

    # 1) INIT
    media_id = init_upload(file_size)
    if not media_id:
        print("INIT failed, cannot proceed.")
        return
    print(f"[INFO] INIT successful -> media_id = {media_id}")

    # 2) APPEND
    success = append_upload(media_id)
    if not success:
        print("[ERROR] APPEND step failed; cannot proceed to FINALIZE.")
        return
    print("[INFO] APPEND successful.")

    # 3) FINALIZE
    fin = finalize_upload(media_id)
    if not fin:
        print("[ERROR] FINALIZE failed, got no JSON response.")
        return

    print("[INFO] FINALIZE done. Full response JSON:")
    print(fin)

if __name__ == "__main__":
    main()
