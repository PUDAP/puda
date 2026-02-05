"""
BiologicMachine class for handling Biologic device commands.

This module provides a wrapper around easy_biologic that enables dynamic command
handling via getattr, allowing command-based execution patterns for Biologic
electrochemical testing devices.
"""
import logging
from typing import Dict, Any, Type
import easy_biologic as ebl
import easy_biologic.base_programs as blp

logger = logging.getLogger(__name__)


class Biologic:
    """
    Wrapper around easy_biologic that provides command handlers for Biologic devices.
    
    This class wraps easy_biologic.base_programs to allow for dynamic method lookup
    via getattr, enabling command-based execution patterns. Each method (OCV, CA, PEIS, etc.)
    wraps the corresponding base program class and provides a consistent interface.
    
    Example:
        machine = Biologic("192.168.1.2")
        handler = getattr(machine, "OCV", None)  # Get handler dynamically
        result = handler(params={"time": 60}, channels=[1, 2])
    """
    
    def __init__(self, device_ip: str):
        """
        Initialize the Biologic machine.
        
        Args:
            device_ip: IP address of the Biologic device
        """
        self.device = ebl.BiologicDevice(device_ip)
        logger.info("BiologicDevice initialized with IP: %s", device_ip)
    
    def _run_base_program(
        self,
        program_class: Type[blp.BiologicProgram],
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generic helper method to run any base program.
        
        This method handles the common pattern:
        1. Create the program instance with params and kwargs
        2. Run the program (with appropriate signature)
        3. Return the data
        
        Args:
            program_class: The base program class to instantiate (e.g., blp.OCV, blp.CA)
            params: Dictionary of parameters for the program
            **kwargs: Additional keyword arguments:
                - For standard programs: retrieve_data [Default: True]
                - For MPP/MPP_Cycles: data, by_channel, cv
                - channels: Optional list of channel numbers (for constructor)
            
        Returns:
            Dictionary containing the program data
        """
        # Check program class type to determine run signature
        # MPP and MPP_Cycles use: data, by_channel, cv
        # MPP_Tracking uses: folder, by_channel
        # Standard programs use: retrieve_data
        if issubclass(program_class, blp.MPP):
            # MPP/MPP_Cycles style: extract run parameters
            data = kwargs.pop('data', 'data')
            by_channel = kwargs.pop('by_channel', False)
            cv_params = kwargs.pop('cv', {})
            run_kwargs = {'data': data, 'by_channel': by_channel, 'cv': cv_params}
        elif program_class == blp.MPP_Tracking:
            # MPP_Tracking style: extract run parameters
            folder = kwargs.pop('folder', None)
            by_channel = kwargs.pop('by_channel', False)
            run_kwargs = {'folder': folder, 'by_channel': by_channel}
        else:
            # Standard program style: extract retrieve_data
            retrieve_data = kwargs.pop('retrieve_data', True)
            run_kwargs = {'retrieve_data': retrieve_data}
        
        # Create program instance - pass all remaining kwargs directly to constructor
        program = program_class(
            device=self.device,
            params=params,
            **kwargs
        )
        
        # Run the program with appropriate signature
        program.run(**run_kwargs)
        
        return program.data
    
    def OCV(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run OCV (Open Circuit Voltage) test.
        
        Args:
            params: Dictionary containing:
                - time: Test duration in seconds
                - time_interval: Maximum time between readings. [Default: 1]
                - voltage_interval: Maximum interval between voltage readings. [Default: 0.01]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the OCV data (keyed by channel)
        """
        logger.info("Running OCV test: params=%s", params)
        return self._run_base_program(blp.OCV, params, **kwargs)
        
    def CA(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run CA (Chronoamperometry) test.
        
        Args:
            params: Dictionary containing:
                - voltages: List of voltages.
                - durations: List of times in seconds.
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points. [Default: 1]
                - current_interval: Maximum current change between points. [Default: 0.001]
                - current_range: Current range. Use ec_lib.IRange. [Default: IRange.m10]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the CA data (keyed by channel)
        """
        logger.info("Running CA test: params=%s", params)
        return self._run_base_program(blp.CA, params, **kwargs)

  
    def PEIS(
        self,
        params: dict[str, Any],
        **kwargs
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
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dictionary containing the PEIS data (keyed by channel)
        """
        logger.info("Running PEIS test: params=%s", params)
        return self._run_base_program(blp.PEIS, params, **kwargs)


    def GEIS(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run GEIS (Galvanostatic Electrochemical Impedance Spectroscopy) test.
        
        Args:
            params: Dictionary containing:
                - current: Initial current in Ampere.
                - amplitude_current: Sinus amplitude in Ampere.
                - initial_frequency: Initial frequency in Hertz.
                - final_frequency: Final frequency in Hertz.
                - frequency_number: Number of frequencies.
                - duration: Overall duration in seconds.
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. [Default: 1]
                - potential_interval: Maximum interval between points in Volts. [Default: 0.001]
                - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
                - repeat: Number of times to repeat the measurement and average the values for each frequency. [Default: 1]
                - correction: Drift correction. [Default: False]
                - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. [Default: 0]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the GEIS data (keyed by channel)
        """
        logger.info("Running GEIS test: params=%s", params)
        return self._run_base_program(blp.GEIS, params, **kwargs)
      
    def CV(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run CV (Cyclic Voltammetry) test.
        
        Args:
            params: Dictionary containing:
                - start: Start voltage. [Default: 0]
                - end: End voltage. Boundary voltage in forward scan. [Default: 0.5]
                - E2: Boundary voltage in backward scan. [Default: 0]
                - Ef: End voltage in the final cycle scan [Default: 0]
                - step: Voltage step. dEN/1000 [Default: 0.01]
                - rate: Scan rate in V/s. [Default: 0.01]
                - average: Average over points. [Default: False]
                - N_Cycles: Number of cycles. [Default: 0]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the CV data (keyed by channel)
        """
        logger.info("Running CV test: params=%s", params)
        return self._run_base_program(blp.CV, params, **kwargs)
      
    def MPP_Tracking(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run MPP_Tracking (Maximum Power Point Tracking) test.
        
        Args:
            params: Dictionary containing:
                - run_time: Run time in seconds.
                - init_vmpp: Initial v_mpp.
                - probe_step: Voltage step for probe. [Default: 0.005 V]
                - probe_points: Number of data points to collect for probe. [Default: 5]
                - probe_interval: How often to probe in seconds. [Default: 2]
                - record_interval: How often to record a data point in seconds. [Default: 1]
            **kwargs: Additional keyword arguments:
                - channels: Optional list of channel numbers
                - folder: Folder or file for saving data [Default: None]
                - by_channel: Save data by channel [Default: False]
            
        Returns:
            Dictionary containing the MPP_Tracking data (keyed by channel)
        """
        logger.info("Running MPP_Tracking test: params=%s", params)
        return self._run_base_program(blp.MPP_Tracking, params, **kwargs)
    
    def MPP(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run MPP (Maximum Power Point) test.
        
        Makes a CV scan and Voc scan and runs MPP tracking.
        
        Args:
            params: Dictionary containing:
                - run_time: Run time in seconds.
                - probe_step: Voltage step for probe. [Default: 0.005 V]
                - probe_points: Number of data points to collect for probe. [Default: 5]
                - probe_interval: How often to probe in seconds. [Default: 2]
                - record_interval: How often to record a data point in seconds. [Default: 1]
            **kwargs: Additional keyword arguments:
                - channels: Optional list of channel numbers
                - data: Data folder path. [Default: 'data']
                - by_channel: Save data by channel. [Default: False]
                - cv: Parameters passed to CV to find initial MPP, or {} for default. [Default: {}]
            
        Returns:
            Dictionary containing the MPP data (keyed by channel)
        """
        logger.info("Running MPP test: params=%s", params)
        return self._run_base_program(blp.MPP, params, **kwargs)
    
    def MPP_Cycles(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run MPP_Cycles (MPP tracking with periodic CV scans) test.
        
        Args:
            params: Dictionary containing:
                - run_time: Cycle run time in seconds.
                - cycles: Number of cycles to perform.
                - probe_step: Voltage step for probe. [Default: 0.01 V]
                - probe_points: Number of data points to collect for probe. [Default: 5]
                - probe_interval: How often to probe in seconds. [Default: 2]
                - record_interval: How often to record a data point in seconds. [Default: 1]
            **kwargs: Additional keyword arguments:
                - channels: Optional list of channel numbers
                - data: Data folder path. [Default: 'data']
                - by_channel: Save data by channel. [Default: False]
                - cv: Parameters for the CV. [Default: {}]
            
        Returns:
            Dictionary containing the MPP_Cycles data (keyed by channel)
        """
        logger.info("Running MPP_Cycles test: params=%s", params)
        return self._run_base_program(blp.MPP_Cycles, params, **kwargs)

