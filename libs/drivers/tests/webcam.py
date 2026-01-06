"""Tests for camera controller functionality."""

import time
import pytest
from puda_drivers.cv import list_cameras, CameraController


@pytest.fixture
def camera_controller():
    """Fixture to create and connect a camera controller."""
    cam = CameraController(camera_index=4)
    cam.connect()
    yield cam
    if cam.is_connected:
        cam.disconnect()


def test_list_cameras():
    """Test listing available cameras."""
    cameras = list_cameras()
    assert isinstance(cameras, list)
    print(f"Found {len(cameras)} cameras")


# pylint: disable=redefined-outer-name
def test_camera_connection(camera_controller):
    """Test camera connection."""
    assert camera_controller.is_connected, "Camera should be connected"
    print("Camera is connected")


# pylint: disable=redefined-outer-name
def test_capture_image(camera_controller):
    """Test image capture functionality."""
    if camera_controller.is_connected:
        image = camera_controller.capture_image()
        assert image is not None
        print("Image captured successfully")


# pylint: disable=redefined-outer-name
def test_record_video_duration(camera_controller):
    """Test recording video for a specific duration."""
    if camera_controller.is_connected:
        video_path = camera_controller.record_video(duration_seconds=10)
        assert video_path is not None
        print(f"Video recorded: {video_path}")


# pylint: disable=redefined-outer-name
def test_start_stop_video_recording(camera_controller):
    """Test starting and stopping video recording manually."""
    if camera_controller.is_connected:
        print("Camera is connected")
        video_path = camera_controller.start_video_recording()
        time.sleep(3)
        stop_path = camera_controller.stop_video_recording()
        assert stop_path is not None or video_path is not None
        print("Video recording started and stopped successfully")
