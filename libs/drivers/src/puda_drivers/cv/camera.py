"""
Camera controller for image and video capture.

This module provides a Python interface for controlling cameras and webcams
to capture images and videos for laboratory automation applications using OpenCV.
"""

import logging
import time
import threading
from datetime import datetime
from typing import Optional, Union, List, Tuple
from pathlib import Path
import cv2
import numpy as np

logger = logging.getLogger(__name__)


def list_cameras(max_index: int = 10) -> List[Tuple[int, bool, Optional[tuple[int, int]]]]:
    """
    Lists available cameras on the system by testing camera indices.
    
    This is a utility function that can be used independently of any controller instance.
    It's useful for discovering available cameras before initializing a controller.
    
    Args:
        max_index: Maximum camera index to test (default: 10). The function will test
                  indices from 0 to max_index-1.
    
    Returns:
        List of tuples, where each tuple contains (index, is_available, resolution).
        resolution is a (width, height) tuple if available, None otherwise.
    """
    available_cameras = []
    
    for index in range(max_index):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            # Try to read a frame to confirm it's actually working
            ret, _ = cap.read()
            if ret:
                # Get resolution
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                resolution = (width, height) if width > 0 and height > 0 else None
                available_cameras.append((index, resolution))
            cap.release()
        else:
            cap.release()
    
    return available_cameras


class CameraController:
    """
    Controller for cameras and webcams using OpenCV.
    
    This class provides methods for capturing images and videos from cameras.
    Images can be returned as numpy arrays and optionally saved to the captures folder.
    Videos can be recorded for a specified duration or controlled manually with start/stop.
    
    Attributes:
        camera_index: Index or identifier for the camera device
        resolution: Camera resolution as (width, height) tuple
        captures_folder: Path to the folder where captured images and videos are saved
    """
    
    DEFAULT_CAPTURES_FOLDER = "captures"
    
    def __init__(
        self,
        camera_index: Union[int, str] = 0,
        resolution: Optional[tuple[int, int]] = None,
        captures_folder: Union[str, Path, None] = None,
    ):
        """
        Initialize the camera controller.
        
        Args:
            camera_index: Camera device index (0 for default) or device path/identifier
            resolution: Optional resolution as (width, height) tuple
            captures_folder: Path to folder for saving captured images. 
                            Defaults to "captures" in the current working directory.
        """
        self.camera_index = camera_index
        self.resolution = resolution
        self.captures_folder = Path(captures_folder) if captures_folder else Path(self.DEFAULT_CAPTURES_FOLDER)
        self._logger = logging.getLogger(__name__)
        self._camera: Optional[cv2.VideoCapture] = None
        self._is_connected = False
        
        # Video recording state
        self._video_writer: Optional[cv2.VideoWriter] = None
        self._is_recording = False
        self._video_file_path: Optional[Path] = None
        self._fps: float = 30.0  # Default FPS for video recording
        self._recording_thread: Optional[threading.Thread] = None
        self._stop_recording_event: Optional[threading.Event] = None
        
        # Create captures folder if it doesn't exist
        self.captures_folder.mkdir(parents=True, exist_ok=True)
        
        self._logger.info(
            "Camera Controller initialized with camera_index='%s', resolution=%s, captures_folder='%s'",
            camera_index,
            resolution,
            self.captures_folder,
        )
    
    def connect(self) -> None:
        """
        Connect to the camera device.
        
        Raises:
            IOError: If camera connection fails
        """
        if self._is_connected:
            self._logger.warning("Camera already connected. Disconnecting and reconnecting...")
            self.disconnect()
        
        self._logger.info("Connecting to camera %s...", self.camera_index)
        
        try:
            self._camera = cv2.VideoCapture(self.camera_index)
            
            if not self._camera.isOpened():
                raise IOError(f"Could not open camera {self.camera_index}")
            
            # Set resolution if specified
            if self.resolution:
                width, height = self.resolution
                self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self._logger.info("Resolution set to %dx%d", width, height)
            
            self._is_connected = True
            self._logger.info("Successfully connected to camera %s", self.camera_index)
            
        except Exception as e:
            self._camera = None
            self._is_connected = False
            self._logger.error("Error connecting to camera %s: %s", self.camera_index, e)
            raise IOError(f"Error connecting to camera {self.camera_index}: {e}") from e
    
    def disconnect(self) -> None:
        """
        Disconnect from the camera device.
        """
        # Stop any ongoing video recording before disconnecting
        if self._is_recording:
            self._logger.warning("Stopping video recording before disconnecting...")
            self.stop_video_recording()
        
        if self._camera is not None:
            self._logger.info("Disconnecting from camera %s...", self.camera_index)
            self._camera.release()
            self._camera = None
            self._is_connected = False
            self._logger.info("Camera disconnected")
        else:
            self._logger.warning("Camera already disconnected or was never connected")
    
    @property
    def is_connected(self) -> bool:
        """
        Check if the camera is currently connected.
        
        Returns:
            True if connected, False otherwise
        """
        return self._is_connected and self._camera is not None and self._camera.isOpened()
    
    def capture_image(
        self, 
        save: bool = False, 
        filename: Optional[Union[str, Path]] = None
    ) -> np.ndarray:
        """
        Capture a single image from the camera.
        
        Args:
            save: If True, save the image to the captures folder
            filename: Optional filename for the saved image. If not provided and save=True,
                     a timestamped filename will be generated. If provided without extension,
                     .jpg will be added.
        
        Returns:
            Captured image as a numpy array (BGR format)
            
        Raises:
            IOError: If camera is not connected or capture fails
        """
        if not self.is_connected:
            raise IOError("Camera is not connected. Call connect() first.")
        
        self._logger.info("Capturing image...")
        
        ret, frame = self._camera.read()
        
        if not ret or frame is None:
            self._logger.error("Failed to capture frame from camera")
            raise IOError("Failed to capture frame from camera")
        
        self._logger.info("Image captured successfully (shape: %s)", frame.shape)
        
        # Save image if requested
        if save:
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"capture_{timestamp}.jpg"
            
            file_path = Path(filename)
            # If filename doesn't have an extension, add .jpg
            if not file_path.suffix:
                file_path = file_path.with_suffix(".jpg")
            
            # If filename is not absolute, save to captures folder
            if not file_path.is_absolute():
                file_path = self.captures_folder / file_path
            
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            cv2.imwrite(str(file_path), frame)
            self._logger.info("Image saved to %s", file_path)
        
        return frame
    
    def set_resolution(self, width: int, height: int) -> None:
        """
        Set the camera resolution.
        
        Args:
            width: Image width in pixels
            height: Image height in pixels
        """
        self.resolution = (width, height)
        self._logger.info("Resolution set to %dx%d", width, height)
        
        # Apply resolution to camera if connected
        if self.is_connected:
            self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self._logger.info("Resolution applied to camera")
    
    def start_video_recording(
        self,
        filename: Optional[Union[str, Path]] = None,
        fps: Optional[float] = None
    ) -> Path:
        """
        Start recording a video.
        
        Args:
            filename: Optional filename for the video. If not provided, a timestamped
                    filename will be generated. If provided without extension, .mp4 will be added.
            fps: Optional frames per second for the video. Defaults to 30.0 if not specified.
        
        Returns:
            Path to the video file where recording is being saved
            
        Raises:
            IOError: If camera is not connected or recording fails to start
            ValueError: If already recording
        """
        if not self.is_connected:
            raise IOError("Camera is not connected. Call connect() first.")
        
        if self._is_recording:
            raise ValueError("Video recording is already in progress. Call stop_video_recording() first.")
        
        # Generate filename if not provided
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"video_{timestamp}.mp4"
        
        file_path = Path(filename)
        # If filename doesn't have an extension, add .mp4
        if not file_path.suffix:
            file_path = file_path.with_suffix(".mp4")
        
        # If filename is not absolute, save to captures folder
        if not file_path.is_absolute():
            file_path = self.captures_folder / file_path
        
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get current camera resolution
        width = int(self._camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Use provided FPS or default
        fps = fps if fps is not None else self._fps
        
        # Define codec and create VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self._video_writer = cv2.VideoWriter(str(file_path), fourcc, fps, (width, height))
        
        if not self._video_writer.isOpened():
            self._video_writer = None
            raise IOError(f"Failed to initialize video writer for {file_path}")
        
        self._is_recording = True
        self._video_file_path = file_path
        self._fps = fps
        
        # Start background thread to continuously capture frames
        self._stop_recording_event = threading.Event()
        self._recording_thread = threading.Thread(target=self._capture_frames_loop, daemon=True)
        self._recording_thread.start()
        
        self._logger.info("Started video recording to %s (FPS: %.1f, Resolution: %dx%d)", 
                         file_path, fps, width, height)
        
        return file_path
    
    def _capture_frames_loop(self) -> None:
        """
        Internal method that continuously captures frames and writes them to the video.
        Runs in a background thread while recording is active.
        """
        frame_interval = 1.0 / self._fps if self._fps > 0 else 0.033  # Default to ~30 FPS
        
        while self._is_recording and not self._stop_recording_event.is_set():
            if self._video_writer is None or self._camera is None:
                break
            
            ret, frame = self._camera.read()
            if ret and frame is not None:
                self._video_writer.write(frame)
            
            time.sleep(frame_interval)
        
        self._logger.debug("Frame capture loop stopped")
    
    def stop_video_recording(self) -> Optional[Path]:
        """
        Stop recording a video.
        
        Returns:
            Path to the saved video file, or None if no recording was in progress
            
        Raises:
            IOError: If video writer fails to release
        """
        if not self._is_recording:
            self._logger.warning("No video recording in progress")
            return None
        
        self._logger.info("Stopping video recording...")
        
        # Signal the recording thread to stop
        self._is_recording = False
        if self._stop_recording_event is not None:
            self._stop_recording_event.set()
        
        # Wait for the recording thread to finish
        if self._recording_thread is not None and self._recording_thread.is_alive():
            self._recording_thread.join(timeout=2.0)
        
        # Release video writer
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
        
        file_path = self._video_file_path
        self._video_file_path = None
        self._recording_thread = None
        self._stop_recording_event = None
        
        if file_path and file_path.exists():
            self._logger.info("Video saved to %s", file_path)
        else:
            self._logger.warning("Video file may not have been saved correctly")
        
        return file_path
    
    def record_video(
        self,
        duration_seconds: float,
        filename: Optional[Union[str, Path]] = None,
        fps: Optional[float] = None
    ) -> Path:
        """
        Record a video for a specified duration.
        
        Args:
            duration_seconds: Duration of the video in seconds
            filename: Optional filename for the video. If not provided, a timestamped
                    filename will be generated. If provided without extension, .mp4 will be added.
            fps: Optional frames per second for the video. Defaults to 30.0 if not specified.
        
        Returns:
            Path to the saved video file
            
        Raises:
            IOError: If camera is not connected or recording fails
            ValueError: If duration is not positive
        """
        if not self.is_connected:
            raise IOError("Camera is not connected. Call connect() first.")
        
        if duration_seconds <= 0:
            raise ValueError(f"Duration must be positive, got {duration_seconds}")
        
        # Start recording
        file_path = self.start_video_recording(filename=filename, fps=fps)
        
        self._logger.info("Recording video for %.2f seconds...", duration_seconds)
        
        start_time = time.time()
        frame_count = 0
        
        try:
            while time.time() - start_time < duration_seconds:
                ret, frame = self._camera.read()
                if ret and frame is not None:
                    self._video_writer.write(frame)
                    frame_count += 1
                else:
                    self._logger.warning("Failed to read frame during video recording")
                    break
        finally:
            # Always stop recording, even if there was an error
            self.stop_video_recording()
        
        actual_duration = time.time() - start_time
        self._logger.info("Video recording completed: %.2f seconds, %d frames (%.1f FPS actual)", 
                         actual_duration, frame_count, frame_count / actual_duration if actual_duration > 0 else 0)
        
        return file_path

