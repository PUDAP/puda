import time
from puda_drivers.cv import list_cameras, CameraController


# print(list_cameras())

camera = CameraController(camera_index=4)
camera.connect()

# Image capture
# if camera.is_connected:
#     print("Camera is connected")
#     camera.capture_image()
#     camera.disconnect()

# Video recording
# if camera.is_connected:
#     print("Camera is connected")
#     camera.record_video(duration_seconds=10)
#     camera.disconnect()
    
# video recording
if camera.is_connected:
    print("Camera is connected")
    camera.start_video_recording()
    time.sleep(3)
    camera.stop_video_recording()
    camera.disconnect()