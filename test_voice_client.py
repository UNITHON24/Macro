# test_voice_client.py
# 음성 서버 테스트용 클라이언트

import requests
import json
import time

def test_voice_server():
    """음성 서버 테스트"""
    base_url = "http://localhost:8080"
    
    print("=== 음성 서버 테스트 ===")
    
    # 1. 서버 상태 확인
    try:
        response = requests.get(f"{base_url}/status")
        if response.status_code == 200:
            status = response.json()
            print(f"✅ 서버 상태: {status}")
        else:
            print(f"❌ 서버 상태 확인 실패: {response.status_code}")
            return
    except requests.exceptions.ConnectionError:
        print("❌ 서버에 연결할 수 없습니다. voiceServer.py를 먼저 실행하세요.")
        return
    
    # 2. 음성파일 전송 테스트 (더미 데이터)
    print("\n=== 음성파일 전송 테스트 ===")
    
    # 간단한 더미 오디오 데이터 (WAV 헤더 + 무음)
    dummy_wav = (
        b'RIFF' +           # RIFF 헤더
        b'\x24\x00\x00\x00' +  # 파일 크기
        b'WAVE' +           # WAVE 형식
        b'fmt ' +           # 포맷 청크
        b'\x10\x00\x00\x00' +  # 포맷 청크 크기
        b'\x01\x00' +       # 오디오 포맷 (PCM)
        b'\x01\x00' +       # 채널 수 (모노)
        b'\x44\xAC\x00\x00' +  # 샘플레이트 (44100)
        b'\x88\x58\x01\x00' +  # 바이트레이트
        b'\x02\x00' +       # 블록 얼라인
        b'\x10\x00' +       # 비트퍼샘플
        b'data' +           # 데이터 청크
        b'\x00\x00\x00\x00' +  # 데이터 크기
        b'\x00\x00' * 1000      # 무음 데이터 (1초)
    )
    
    try:
        headers = {
            'Content-Type': 'audio/wav',
            'Content-Length': str(len(dummy_wav))
        }
        
        response = requests.post(
            base_url,
            data=dummy_wav,
            headers=headers
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 음성파일 전송 성공: {result}")
        else:
            print(f"❌ 음성파일 전송 실패: {response.status_code}")
            print(f"응답: {response.text}")
            
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    
    # 3. 재생 상태 확인
    print("\n=== 재생 상태 확인 ===")
    time.sleep(2)  # 재생 시간 대기
    
    try:
        response = requests.get(f"{base_url}/status")
        if response.status_code == 200:
            status = response.json()
            print(f"재생 후 상태: {status}")
        else:
            print(f"상태 확인 실패: {response.status_code}")
    except Exception as e:
        print(f"상태 확인 오류: {e}")

if __name__ == "__main__":
    test_voice_server()
