"""
BiologicMachine class for handling Biologic device commands.

This module provides command handlers for the Biologic electrochemical testing device.
"""
import logging
from typing import Dict, Any, Optional
import easy_biologic as ebl
import easy_biologic.base_programs as blp

logger = logging.getLogger(__name__)


class BiologicMachine:
    """
    Machine class that wraps BiologicDevice and provides command handlers.
    """
    
    def __init__(self, device_ip: str):
        """
        Initialize the Biologic machine.
        
        Args:
            device_ip: IP address of the Biologic device
        """
        self.device = ebl.BiologicDevice(device_ip)
        logger.info("BiologicDevice initialized with IP: %s", device_ip)
    
    def OCV(
        self,
        params: dict[str, Any],
        channels: Optional[list[int]] = None,
        save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run OCV (Open Circuit Voltage) test.
        
        Args:
            params: Dictionary containing:
                - time: Test duration in seconds
                - time_interval: Maximum time between readings. [Default: 1]
                - voltage_interval: Maximum interval between voltage readings. [Default: 0.01]
            channels: Optional list of channel numbers to test
            save_path: Optional path to save the OCV data CSV file
            
        Returns:
            Dictionary containing:
            - average_voltage: Average voltage across all channels
            - voc: Dictionary mapping channel to average voltage
            - data_path: Path where data was saved (only if save_path was provided)
        """
        logger.info("Running OCV test: params=%s", params)
        
        # Create and run OCV test
        ocv = blp.OCV(
            device=self.device,
            params=params,
            channels=channels,
            save_path=save_path
        )
        
        ocv.run('data')
        if save_path:
            ocv.save_data(save_path)
        
        return ocv.data

        
    def CA(
      self,
      params: dict[str, Any],
      channels: Optional[list[int]] = None,
      save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run CA (Chronoamperometry) test.
        
        Args:
          params: Dictionary containing
            - voltages: List of voltages.
            - durations: List of times in seconds.
            - vs_initial: If step is vs. initial or previous. [Default: False]
            - time_interval: Maximum time interval between points. [Default: 1]
            - current_interval: Maximum current change between points. [Default: 0.001]
            - current_range: Current range. Use ec_lib.IRange. [Default: IRange.m10 ]
          channels: Optional list of channel numbers to test
          save_path: Optional path to save the CA data CSV file
        """
        logger.info("Running CA test: params=%s", params)

        ca = blp.CA(
          self.device,
          params=params,
          channels=channels,
          save_path=save_path
        )
        ca.run('data')

        if save_path:
            ca.save_data(save_path)
            logger.info("CA test completed. Data saved to: %s", save_path)
        else:
            logger.info("CA test completed.")

        return ca.data

  
    def PEIS(
        self,
        params: dict[str, Any],
        channels: Optional[list[int]] = None,
        save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run PEIS (Potentiostatic Electrochemical Impedance Spectroscopy) test.
        
        Args:
            params: Dictionary containing:
              - voltage: Initial potential in Volts.
              - amplitude_voltage: Sinus amplitude in Volts.
              - initial_frequency: Initial frequency in Hertz.
              - final_frequency: Final frequency in Hertz.
              - frequency_number: Number of frequencies.
              - duration: Overall duration in seconds.
              - vs_initial: If step is vs. initial or previous. [Default: False]
              - time_interval: Maximum time interval between points in seconds. [Default: 1]
              - current_interval: Maximum time interval between points in Amps. [Default: 0.001]
              - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
              - repeat: Number of times to repeat the measurement and average the values for each frequency. [Default: 1]
              - correction: Drift correction. [Default: False]
              - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. [Default: 0]
            channels: Optional list of channel numbers to test
            save_path: Optional path to save the PEIS data CSV file

        Returns:
            Dictionary containing:
            - data_path: Path where data was saved (only if save_path was provided)
        """

        logger.info("Running PEIS test: params=%s", params)
        
        # Create and run PEIS test
        peis = blp.PEIS(
            device=self.device,
            params=params,
            channels=channels,
            save_path=save_path
        )
        
        peis.run('data')
        if save_path:
            peis.save_data(save_path)
            logger.info("PEIS test completed. Data saved to: %s", save_path)
        else:
            logger.info("PEIS test completed.")

        return peis.data


    def GEIS(
      self,
      params: dict[str, Any],
      channels: Optional[list[int]] = None,
      save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run GEIS (Galvanostatic Electrochemical Impedance Spectroscopy) test.
        
        Args:
          params: Dictionary containing
            - current: Initial current in Ampere.
            - amplitude_current: Sinus amplitude in Ampere.
            - initial_frequency: Initial frequency in Hertz.
            - final_frequency: Final frequency in Hertz.
            - frequency_number: Number of frequencies.
            - duration: Overall duration in seconds.
            - vs_initial: If step is vs. initial or previous. [Default: False]
            - time_interval: Maximum time interval between points in seconds. [Default: 1]
            - current_interval: Maximum time interval between points in Amps. [Default: 0.001]
            - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
            - repeat: Number of times to repeat the measurement and average the values for each frequency. [Default: 1]
            - correction: Drift correction. [Default: False]
            - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. [Default: 0]
          channels: Optional list of channel numbers to test
          save_path: Optional path to save the GEIS data CSV file
        """
        logger.info("Running GEIS test: params=%s", params)

        geis = blp.GEIS(
          device=self.device,
          params=params,
          channels=channels,
          save_path=save_path
        )
        geis.run('data')
        if save_path:
            geis.save_data(save_path)
            logger.info("GEIS test completed. Data saved to: %s", save_path)
        else:
            logger.info("GEIS test completed.")
            
        return geis.data
      
    def CV(
      self,
      params: dict[str, Any],
      channels: Optional[list[int]] = None,
      save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run CV (Chronoamperometry) test.
        
        Args:
          params: Dictionary containing
            - start: Start voltage. [Default: 0]
            - end: End voltage. Boundary voltage in forward scan. [Default: 0.5]
            - E2: Boundary voltage in backward scan. [Default: 0]
            - Ef: End voltage in the final cycle scan [Default: 0]
            - step: Voltage step. dEN/1000 [Default: 0.01]
            - rate: Scan rate in V/s. [Default: 0.01]
            - average: Average over points. [Default: False]
          channels: Optional list of channel numbers to test
          save_path: Optional path to save the CV data CSV file
        """
        logger.info("Running CV test: params=%s", params)
        cv = blp.CV(
          device=self.device,
          params=params,
          channels=channels,
          save_path=save_path
        )
        cv.run('data')
        if save_path:
            cv.save_data(save_path)
            logger.info("CV test completed. Data saved to: %s", save_path)
        else:
            logger.info("CV test completed.")

        return cv.data
      
    def MPP_Tracking(
      self,
      params: dict[str, Any],
      channels: Optional[list[int]] = None,
      save_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run MPP_Tracking (Maximum Power Point Tracking) test.
        
        Args:
          params: Dictionary containing
            - run_time: Run time in seconds.
            - init_vmpp: Initial v_mpp.
            - probe_step: Voltage step for probe. [Default: 0.01 V]
            - probe_points: Number of data points to collect for probe. [Default: 5]
            - probe_interval: How often to probe in seconds. [Default: 2]
            - record_interval: How often to record a data point in seconds. [Default: 1]
          channels: Optional list of channel numbers to test
          save_path: Optional path to save the MPP_Tracking data CSV file
        """
        logger.info("Running MPP_Tracking test: params=%s", params)

        mpp_tracking = blp.MPP_Tracking(
          device=self.device,
          params=params,
          channels=channels,
          save_path=save_path
        )
        mpp_tracking.run('data')
        if save_path:
            mpp_tracking.save_data(save_path)
            logger.info("MPP_Tracking test completed. Data saved to: %s", save_path)
        else:
            logger.info("MPP_Tracking test completed.")
        
        return mpp_tracking.data