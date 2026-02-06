"""
BiologicMachine class for handling Biologic device commands.

This module provides a wrapper around easy_biologic that enables dynamic command
handling via getattr, allowing command-based execution patterns for Biologic
electrochemical testing devices.
"""
import sys
import logging
from typing import Dict, Any, Type

logger = logging.getLogger(__name__)

# only import easy_biologic on windows
if sys.platform == "win32":
    import easy_biologic as ebl
    import easy_biologic.base_programs as blp
    from easy_biologic.lib import ec_lib
else:
    ebl = None
    blp = None
    ec_lib = None

class Params(dict):
    """
    A dict subclass that supports both dict-like operations and attribute access.
    
    This allows easy_biologic programs to use both:
    - if "sweep" in params:  (dict membership)
    - if params.sweep == "log":  (attribute access)
    """
    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(f"'Params' object has no attribute '{name}'")
    
    def __setattr__(self, name, value):
        self[name] = value

# Helper function to convert IRange string to IRange object
def _convert_irange_string(irange_str: str):
    """
    Convert a string representation of IRange to the actual IRange object.
    
    Supports formats:
    - "IRange.m10" -> IRange.m10
    - "m10" -> IRange.m10
    - "IRange.p100" -> IRange.p100
    - etc.
    
    Args:
        irange_str: String representation of IRange (e.g., "IRange.m10" or "m10")
        
    Returns:
        IRange object if conversion successful, otherwise returns the original string
        
    Raises:
        ValueError: If the string doesn't match a valid IRange value
    """
    if not isinstance(irange_str, str):
        return irange_str
    
    # Remove "IRange." prefix if present
    if irange_str.startswith("IRange."):
        irange_name = irange_str[7:]  # Remove "IRange." prefix
    else:
        irange_name = irange_str
    
    # Try to get the IRange attribute
    try:
        return getattr(ec_lib.IRange, irange_name)
    except AttributeError:
        raise ValueError(f"Invalid IRange value: {irange_str}. Valid values are: p100, n1, u1, m1, m10, a1")


class Biologic:
    """
    Wrapper around easy_biologic that provides command handlers for Biologic devices.
    
    This class wraps easy_biologic.base_programs to allow for dynamic method lookup
    via getattr, enabling command-based execution patterns. Each method (OCV, CA, PEIS, etc.)
    wraps the corresponding base program class and provides a consistent interface.
    
    Example:
        machine = BiologicMachine("192.168.1.2")
        handler = getattr(machine, "OCV", None)  # Get handler dynamically
        result = handler(params={"time": 60}, channels=[1, 2])
    """
    
    def __init__(self, device_ip: str):
        """
        Initialize the Biologic machine.
        
        Args:
            device_ip: IP address of the Biologic device
        """
        self.device_ip = device_ip
        self.device = None
        logger.info("BiologicMachine initialized with IP: %s (device not yet started)", device_ip)
    
    def startup(self):
        """
        Start up the Biologic device connection.
        
        This method initializes the BiologicDevice and should be called
        before running any commands. This allows for delayed initialization
        and better control over when the device connection is established.
        """
        if self.device is not None:
            logger.warning("BiologicDevice already initialized, skipping startup")
            return
        
        self.device = ebl.BiologicDevice(self.device_ip)
        logger.info("BiologicDevice started with IP: %s", self.device_ip)
    
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
            
        Raises:
            RuntimeError: If startup() has not been called to initialize the device
        """
        if self.device is None:
            raise RuntimeError("Device not initialized. Call startup() before running programs.")
        # Convert current_range from string to IRange object if needed
        if 'current_range' in params and isinstance(params['current_range'], str):
            try:
                params['current_range'] = _convert_irange_string(params['current_range'])
            except (ValueError, AttributeError) as e:
                logger.warning("Failed to convert current_range string '%s' to IRange object: %s. Using as-is.", 
                             params['current_range'], e)
        
        # Convert dict to Params object for all programs
        params = Params(params)
        
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

    ### Base programs ###
    
    def OCV(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run OCV (Open Circuit Voltage) test.
        
        Args:
            params: Dictionary containing:
                - time: Test duration in seconds (float, > 0).
                - time_interval: Maximum time between readings (float, > 0.0002 s). [Default: 1]
                - voltage_interval: Maximum interval between voltage readings (float, 1e-6 to 1 V). [Default: 0.01]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the OCV data (keyed by channel)
        """
        logger.info("Running OCV test: params=%s, kwargs=%s", params, kwargs)
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
                - voltages: List of voltages in Volts (list[float], each element: -10 to 10 V).
                - durations: List of times in seconds (list[float], each element: > 0).
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points (float, 0.0002 to 1000 s). [Default: 1]
                - current_interval: Maximum current change between points (float, ±1e-12 to current_range A). [Default: 0.001]
                - current_range: Current range. Use ec_lib.IRange (typically ±1 A). Available: IRange.p100 (±100 pA), IRange.n1 (±1 nA), IRange.u1 (±1 µA), IRange.m1 (±1 mA), IRange.m10 (±10 mA), IRange.a1 (±1 A). Can be provided as a string (e.g., "IRange.m10") which will be automatically converted. [Default: IRange.m10]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the CA data (keyed by channel)
        """
        logger.info("Running CA test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.CA, params, **kwargs)

    def CP(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run CP (Chronoamperometry) test.

        Args:
            params: Dictionary containing:
                - currents: List of currents in Amps. (list[float], each element: 1e-9 to current_range A)
                - durations: List of times in seconds. (list[float], each element: > 0)
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. (float, 0.0002 to 1000). [Default: 1]
                - voltage_interval: Maximum voltage change between points in Volts. (float, 1e-4 to 1e-2). [Default: 0.001]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
        """
        logger.info("Running CP test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.CP, params, **kwargs)

  
    def PEIS(
        self,
        params: dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run PEIS (Potentiostatic Electrochemical Impedance Spectroscopy) test.
        
        Args:
            params: Dictionary containing:
                - voltage: Initial potential in Volts. (float, -10 to 10 V)
                - amplitude_voltage: Sinus amplitude in Volts (float, 1e-4 to 0.5 V).
                - initial_frequency: Initial frequency in Hertz (float, 10 µHz to 1 MHz).
                - final_frequency: Final frequency in Hertz (float, 10 µHz to 1 MHz).
                - frequency_number: Number of frequencies (int, 1 to 1000).
                - duration: Overall duration in seconds. (float, > 0)
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. (float, 0.0002 to 1000 s). [Default: 1]
                - current_interval: Maximum time interval between points in Amps. (float, 1e-12 A to current_range A). [Default: 0.001]
                - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
                - repeat: Number of times to repeat the measurement and average the values for each frequency. (int, 1 to 10). [Default: 1]
                - correction: Drift correction. [Default: False]
                - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. (float, 0 to 5). [Default: 0]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]

        Returns:
            Dictionary containing the PEIS data (keyed by channel)
        """
        logger.info("Running PEIS test: params=%s, kwargs=%s", params, kwargs)
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
                - current: Initial current in Ampere. (float, 1e-12 to current_range A)
                - amplitude_current: Sinus amplitude in Ampere. (float, 1e-9 to current_range A)
                - initial_frequency: Initial frequency in Hertz. (float, 10 µHz to 1 MHz)
                - final_frequency: Final frequency in Hertz. (float, 10 µHz to 1 MHz)
                - frequency_number: Number of frequencies. (int, 1 to 1000)
                - duration: Overall duration in seconds. (float, > 0)
                - vs_initial: If step is vs. initial or previous. [Default: False]
                - time_interval: Maximum time interval between points in seconds. (float, 0.0002 to 1000 s). [Default: 1]
                - potential_interval: Maximum interval between points in Volts. [Default: 0.001]
                - sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']
                - repeat: Number of times to repeat the measurement and average the values for each frequency. (int, 1 to 10). [Default: 1]
                - correction: Drift correction. [Default: False]
                - wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. (float, 0 to 5). [Default: 0]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the GEIS data (keyed by channel)
        """
        logger.info("Running GEIS test: params=%s, kwargs=%s", params, kwargs)
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
                - start: Start voltage. (float, -10 to 10 V). [Default: 0]
                - end: End voltage. Boundary voltage in forward scan. (float, -10 to 10 V). [Default: 0.5]
                - E2: Boundary voltage in backward scan. (float, -10 to 10 V). [Default: 0]
                - Ef: End voltage in the final cycle scan (float, -10 to 10 V). [Default: 0]
                - step: Voltage step. dEN/1000 (float, 1e-4 to 0.05 V). [Default: 0.01]
                - rate: Scan rate in V/s. (float, 1e-5 to 100 V/s). [Default: 0.01]
                - average: Average over points. (bool). [Default: False]
                - N_Cycles: Number of cycles. (int, 0 to 1000). [Default: 0]
            **kwargs: Additional keyword arguments passed to program constructor:
                - channels: Optional list of channel numbers
                - retrieve_data: Whether to automatically retrieve data after running [Default: True]
            
        Returns:
            Dictionary containing the CV data (keyed by channel)
        """
        logger.info("Running CV test: params=%s, kwargs=%s", params, kwargs)
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
        logger.info("Running MPP_Tracking test: params=%s, kwargs=%s", params, kwargs)
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
        logger.info("Running MPP test: params=%s, kwargs=%s", params, kwargs)
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
        logger.info("Running MPP_Cycles test: params=%s, kwargs=%s", params, kwargs)
        return self._run_base_program(blp.MPP_Cycles, params, **kwargs)