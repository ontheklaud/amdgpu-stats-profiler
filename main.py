import json
import time
import subprocess
import re
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional

# Configuration from environment variables
DEBUG_MODE = os.environ.get('AMD_GPU_MONITOR_DEBUG', '').lower() in ('true', '1', 'yes', 'on')
QUIET_MODE = os.environ.get('AMD_GPU_MONITOR_QUIET', '').lower() in ('true', '1', 'yes', 'on')
ENABLE_AMDSMI = not os.environ.get('AMD_GPU_MONITOR_DISABLE_AMDSMI', '').lower() in ('true', '1', 'yes', 'on')
ENABLE_ROCM_SMI = not os.environ.get('AMD_GPU_MONITOR_DISABLE_ROCM_SMI', '').lower() in ('true', '1', 'yes', 'on')

# Sampling interval configuration
try:
    SAMPLING_INTERVAL = float(os.environ.get('AMD_GPU_MONITOR_INTERVAL', '1.0'))
    if SAMPLING_INTERVAL <= 0:
        SAMPLING_INTERVAL = 1.0
except ValueError:
    SAMPLING_INTERVAL = 1.0

def debug_print(message: str):
    """Print debug message only if debug mode is enabled"""
    if DEBUG_MODE:
        print(f"DEBUG: {message}")

def info_print(message: str):
    """Print info message unless quiet mode is enabled"""
    if not QUIET_MODE:
        print(message)

@dataclass
class GPUMetrics:
    gpu_id: int
    timestamp: str
    power_watts: Optional[float] = None
    temperature_celsius: Optional[float] = None
    utilization_percent: Optional[float] = None
    vram_usage_percent: Optional[float] = None
    sclk_mhz: Optional[float] = None
    mclk_mhz: Optional[float] = None
    energy_accumulator: Optional[int] = None
    counter_resolution: Optional[float] = None

class AMDGPUMonitor:
    def __init__(self, output_dir: str = "gpu_monitoring_data", sampling_interval: Optional[float] = None):
        self.output_dir = output_dir
        self.sampling_interval = sampling_interval if sampling_interval is not None else SAMPLING_INTERVAL
        self.amdsmi_available = False
        self.rocm_smi_available = False
        self.gpu_handles = []
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Check available monitoring methods
        self._check_monitoring_tools()
    
    def _check_monitoring_tools(self):
        """Check which monitoring tools are available"""
        # Check amdsmi
        if ENABLE_AMDSMI:
            try:
                import amdsmi
                amdsmi.amdsmi_init()
                gpu_handles = amdsmi.amdsmi_get_processor_handles()
                if gpu_handles:
                    self.amdsmi_available = True
                    self.gpu_handles = gpu_handles
                    info_print(f"amdsmi: {len(gpu_handles)} GPU(s) detected")
                else:
                    debug_print("amdsmi: No GPUs detected")
                amdsmi.amdsmi_shut_down()
            except Exception as e:
                debug_print(f"amdsmi not available: {e}")
        else:
            debug_print("amdsmi disabled via environment variable")
        
        # Check rocm-smi
        if ENABLE_ROCM_SMI:
            try:
                result = subprocess.run(['rocm-smi', '--version'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    self.rocm_smi_available = True
                    info_print("rocm-smi: Available")
            except Exception as e:
                debug_print(f"rocm-smi not available: {e}")
        else:
            debug_print("rocm-smi disabled via environment variable")
    
    def _get_amdsmi_metrics(self) -> List[GPUMetrics]:
        """Get metrics using amdsmi with latest API"""
        if not self.amdsmi_available:
            return []
        
        try:
            import amdsmi
            amdsmi.amdsmi_init()
            
            # Re-get handles each time to avoid stale handles
            current_handles = amdsmi.amdsmi_get_processor_handles()
            metrics_list = []
            timestamp = datetime.now().isoformat()
            
            for i, handle in enumerate(current_handles):
                metrics = GPUMetrics(gpu_id=i, timestamp=timestamp)
                
                # Get comprehensive GPU metrics using the new unified function
                try:
                    gpu_metrics = amdsmi.amdsmi_get_gpu_metrics_info(handle)
                    debug_print(f"amdsmi GPU {i}: Full metrics: {gpu_metrics}")
                    
                    # Temperature - use temperature_edge from gpu_metrics_info
                    if 'temperature_edge' in gpu_metrics and gpu_metrics['temperature_edge'] is not None:
                        metrics.temperature_celsius = float(gpu_metrics['temperature_edge'])
                        debug_print(f"amdsmi GPU {i}: Edge Temperature: {metrics.temperature_celsius}°C")
                    elif 'temperature_hotspot' in gpu_metrics and gpu_metrics['temperature_hotspot'] is not None:
                        metrics.temperature_celsius = float(gpu_metrics['temperature_hotspot'])
                        debug_print(f"amdsmi GPU {i}: Hotspot Temperature: {metrics.temperature_celsius}°C")
                    
                    # Power - use average_socket_power from gpu_metrics_info
                    if 'average_socket_power' in gpu_metrics and gpu_metrics['average_socket_power'] is not None:
                        metrics.power_watts = float(gpu_metrics['average_socket_power'])
                        debug_print(f"amdsmi GPU {i}: Average Socket Power: {metrics.power_watts}W")
                    elif 'current_socket_power' in gpu_metrics and gpu_metrics['current_socket_power'] is not None:
                        metrics.power_watts = float(gpu_metrics['current_socket_power'])
                        debug_print(f"amdsmi GPU {i}: Current Socket Power: {metrics.power_watts}W")
                    
                    # GPU Activity - use average_gfx_activity from gpu_metrics_info
                    if 'average_gfx_activity' in gpu_metrics and gpu_metrics['average_gfx_activity'] is not None:
                        metrics.utilization_percent = float(gpu_metrics['average_gfx_activity'])
                        debug_print(f"amdsmi GPU {i}: GFX Activity: {metrics.utilization_percent}%")
                    
                    # Clock frequencies
                    if 'average_gfxclk_frequency' in gpu_metrics and gpu_metrics['average_gfxclk_frequency'] is not None:
                        metrics.sclk_mhz = float(gpu_metrics['average_gfxclk_frequency'])
                        debug_print(f"amdsmi GPU {i}: Average GFXCLK: {metrics.sclk_mhz}MHz")
                    elif 'current_gfxclk' in gpu_metrics and gpu_metrics['current_gfxclk'] is not None:
                        metrics.sclk_mhz = float(gpu_metrics['current_gfxclk'])
                        debug_print(f"amdsmi GPU {i}: Current GFXCLK: {metrics.sclk_mhz}MHz")
                    
                    if 'average_uclk_frequency' in gpu_metrics and gpu_metrics['average_uclk_frequency'] is not None:
                        metrics.mclk_mhz = float(gpu_metrics['average_uclk_frequency'])
                        debug_print(f"amdsmi GPU {i}: Average UCLK: {metrics.mclk_mhz}MHz")
                    elif 'current_uclk' in gpu_metrics and gpu_metrics['current_uclk'] is not None:
                        metrics.mclk_mhz = float(gpu_metrics['current_uclk'])
                        debug_print(f"amdsmi GPU {i}: Current UCLK: {metrics.mclk_mhz}MHz")
                    
                    # Energy accumulator from gpu_metrics_info
                    if 'energy_accumulator' in gpu_metrics and gpu_metrics['energy_accumulator'] is not None:
                        metrics.energy_accumulator = int(gpu_metrics['energy_accumulator'])
                        # According to API doc: energy_accumulator with 15.3 uJ resolution over 1ns
                        metrics.counter_resolution = 15.3
                        debug_print(f"amdsmi GPU {i}: Energy Accumulator: {metrics.energy_accumulator} (15.3 uJ resolution)")
                    
                except Exception as e:
                    debug_print(f"amdsmi GPU {i}: gpu_metrics_info failed: {e}")
                    # Fallback to individual API calls if gpu_metrics_info fails
                    
                    # Fallback: Individual API calls for compatibility
                    try:
                        # Temperature using individual temp API
                        from amdsmi import AmdSmiTemperatureType, AmdSmiTemperatureMetric
                        temp_types = [
                            AmdSmiTemperatureType.EDGE,
                            AmdSmiTemperatureType.HOTSPOT,
                            AmdSmiTemperatureType.JUNCTION
                        ]
                        
                        for temp_type in temp_types:
                            try:
                                temp_result = amdsmi.amdsmi_get_temp_metric(handle, temp_type, AmdSmiTemperatureMetric.CURRENT)
                                if temp_result is not None:
                                    temp_celsius = float(temp_result) / 1000.0  # Convert from millidegrees
                                    if temp_celsius > 0:
                                        metrics.temperature_celsius = temp_celsius
                                        debug_print(f"amdsmi GPU {i}: Temperature (fallback): {temp_celsius}°C from {temp_type}")
                                        break
                            except Exception:
                                continue
                    except Exception as e:
                        debug_print(f"amdsmi GPU {i}: Temperature fallback failed: {e}")
                    
                    # Fallback: Power using individual power API
                    try:
                        power_info = amdsmi.amdsmi_get_power_info(handle)
                        power_val = (power_info.get("current_socket_power") or 
                                    power_info.get("average_socket_power"))
                        if power_val is not None:
                            metrics.power_watts = float(power_val)
                            debug_print(f"amdsmi GPU {i}: Power (fallback): {metrics.power_watts}W")
                    except Exception as e:
                        debug_print(f"amdsmi GPU {i}: Power fallback failed: {e}")
                    
                    # Fallback: GPU Activity using individual activity API
                    try:
                        activity = amdsmi.amdsmi_get_gpu_activity(handle)
                        util_val = activity.get("gfx_activity")
                        if util_val is not None:
                            metrics.utilization_percent = float(util_val)
                            debug_print(f"amdsmi GPU {i}: Utilization (fallback): {metrics.utilization_percent}%")
                    except Exception as e:
                        debug_print(f"amdsmi GPU {i}: Activity fallback failed: {e}")
                    
                    # Fallback: Energy counter using individual energy API
                    try:
                        energy = amdsmi.amdsmi_get_energy_count(handle)
                        # Try both new and old field names
                        energy_val = (energy.get("energy_accumulator") or 
                                    energy.get("power") or 
                                    energy.get("counter"))
                        if energy_val is not None:
                            metrics.energy_accumulator = int(energy_val)
                        
                        resolution = energy.get("counter_resolution", 15.259)  # Default from API
                        metrics.counter_resolution = float(resolution)
                        debug_print(f"amdsmi GPU {i}: Energy (fallback): {metrics.energy_accumulator}, resolution: {metrics.counter_resolution}")
                    except Exception as e:
                        debug_print(f"amdsmi GPU {i}: Energy fallback failed: {e}")
                
                # VRAM usage (separate API call)
                try:
                    vram = amdsmi.amdsmi_get_gpu_vram_usage(handle)
                    vram_used = vram.get("vram_used") 
                    vram_total = vram.get("vram_total") or 1
                    if vram_used is not None and vram_total > 0:
                        metrics.vram_usage_percent = (float(vram_used) / float(vram_total)) * 100
                        debug_print(f"amdsmi GPU {i}: VRAM: {metrics.vram_usage_percent}%")
                except Exception as e:
                    debug_print(f"amdsmi GPU {i}: VRAM failed: {e}")
                
                metrics_list.append(metrics)
            
            amdsmi.amdsmi_shut_down()
            return metrics_list
            
        except Exception as e:
            debug_print(f"amdsmi general error: {e}")
            try:
                import amdsmi
                amdsmi.amdsmi_shut_down()
            except:
                pass
            return []
    
    def _get_rocm_smi_metrics(self) -> List[GPUMetrics]:
        """Get metrics using rocm-smi"""
        if not self.rocm_smi_available:
            return []
        
        try:
            result = subprocess.run(['rocm-smi', '--showall', '--json'],
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                debug_print(f"rocm-smi failed: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            metrics_list = []
            timestamp = datetime.now().isoformat()
            
            for card_key, gpu_data in data.items():
                if not card_key.startswith('card') or not isinstance(gpu_data, dict):
                    continue
                
                gpu_id = int(card_key.replace('card', ''))
                metrics = GPUMetrics(gpu_id=gpu_id, timestamp=timestamp)
                
                # Parse metrics from rocm-smi output
                metrics.power_watts = self._safe_float(gpu_data.get('Current Socket Graphics Package Power (W)'))
                metrics.temperature_celsius = self._safe_float(gpu_data.get('Temperature (Sensor junction) (C)'))
                metrics.utilization_percent = self._safe_float(gpu_data.get('GPU use (%)'))
                metrics.vram_usage_percent = self._safe_float(gpu_data.get('GPU Memory Allocated (VRAM%)'))
                metrics.sclk_mhz = self._safe_float(gpu_data.get('current_gfxclk (MHz)'))
                metrics.mclk_mhz = self._safe_float(gpu_data.get('current_uclk (MHz)'))
                
                # Energy counter parsing - improved based on actual rocm-smi output
                energy_found = False
                
                # Method 1: Use "energy_accumulator" field (new format)
                energy_counter = gpu_data.get('energy_accumulator')
                if isinstance(energy_counter, (str, int, float)):
                    try:
                        counter_value = int(energy_counter)
                        metrics.energy_accumulator = counter_value
                        metrics.counter_resolution = 15.259  # Default resolution
                        energy_found = True
                        debug_print(f"rocm-smi GPU {gpu_id}: Using 'energy_accumulator' = {counter_value}")
                    except ValueError:
                        pass
                
                # Method 2: Use "Energy counter" (raw counter value)
                if not energy_found:
                    energy_counter = gpu_data.get('Energy counter')
                    if isinstance(energy_counter, (str, int, float)):
                        try:
                            counter_value = int(energy_counter)
                            metrics.energy_accumulator = counter_value
                            metrics.counter_resolution = 15.259  # Default resolution
                            energy_found = True
                            debug_print(f"rocm-smi GPU {gpu_id}: Using 'Energy counter' = {counter_value}")
                        except ValueError:
                            pass
                
                # Method 3: Use formatted energy accumulator string
                if not energy_found:
                    energy_acc_key = 'energy_accumulator (15.259uJ (2^-16))'
                    energy_acc_value = gpu_data.get(energy_acc_key)
                    if isinstance(energy_acc_value, (str, int, float)):
                        try:
                            counter_value = int(energy_acc_value)
                            metrics.energy_accumulator = counter_value
                            metrics.counter_resolution = 15.259  # From the key name
                            energy_found = True
                            debug_print(f"rocm-smi GPU {gpu_id}: Using '{energy_acc_key}' = {counter_value}")
                        except ValueError:
                            pass
                
                # Method 4: Use "Accumulated Energy (uJ)" (already converted to microJoules)
                if not energy_found:
                    accumulated_energy = gpu_data.get('Accumulated Energy (uJ)')
                    if isinstance(accumulated_energy, (str, float)):
                        try:
                            # This is already in microJoules, so we use resolution of 1.0
                            energy_uj = float(accumulated_energy)
                            metrics.energy_accumulator = int(energy_uj)
                            metrics.counter_resolution = 1.0  # Already in uJ
                            energy_found = True
                            debug_print(f"rocm-smi GPU {gpu_id}: Using 'Accumulated Energy (uJ)' = {energy_uj}")
                        except ValueError:
                            pass
                
                if not energy_found:
                    debug_print(f"rocm-smi GPU {gpu_id}: No usable energy data found")
                    # Show what energy keys are available for debugging
                    energy_keys = [k for k in gpu_data.keys() if 'energy' in k.lower()]
                    debug_print(f"  Available energy keys: {energy_keys}")
                
                metrics_list.append(metrics)
            
            return metrics_list
            
        except Exception as e:
            debug_print(f"rocm-smi error: {e}")
            return []
    
    def _safe_float(self, value) -> Optional[float]:
        """Safely convert value to float"""
        if value is None or value == 'N/A':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def _save_metrics(self, metrics_list: List[GPUMetrics], filename: str):
        """Save metrics to file"""
        with open(filename, 'a') as f:
            for metrics in metrics_list:
                metrics_dict = {
                    'timestamp': metrics.timestamp,
                    'gpu_id': metrics.gpu_id,
                    'power_watts': metrics.power_watts,
                    'temperature_celsius': metrics.temperature_celsius,
                    'utilization_percent': metrics.utilization_percent,
                    'vram_usage_percent': metrics.vram_usage_percent,
                    'sclk_mhz': metrics.sclk_mhz,
                    'mclk_mhz': metrics.mclk_mhz,
                    'energy_accumulator': metrics.energy_accumulator,
                    'counter_resolution': metrics.counter_resolution
                }
                f.write(json.dumps(metrics_dict) + '\n')
    
    def _calculate_energy_consumption(self, initial_metrics: List[GPUMetrics], 
                                    final_metrics: List[GPUMetrics]) -> float:
        """Calculate total energy consumption in Wh"""
        total_energy_wh = 0.0
        
        # Create lookup for final metrics
        final_lookup = {m.gpu_id: m for m in final_metrics}
        
        for initial in initial_metrics:
            final = final_lookup.get(initial.gpu_id)
            
            if (final and 
                initial.energy_accumulator is not None and 
                final.energy_accumulator is not None and 
                initial.counter_resolution is not None and
                final.energy_accumulator >= initial.energy_accumulator):
                
                # Calculate energy delta in microJoules
                delta_ticks = final.energy_accumulator - initial.energy_accumulator
                delta_uj = delta_ticks * initial.counter_resolution
                # Convert to Watt-hours (1 Wh = 3,600,000,000 uJ)
                energy_wh = delta_uj / 3_600_000_000
                total_energy_wh += energy_wh
                
                debug_print(f"GPU {initial.gpu_id}: {delta_ticks} ticks = {energy_wh:.6f} Wh")
        
        return total_energy_wh
    
    def _generate_report(self, filename: str, start_time: datetime, end_time: datetime,
                        initial_metrics: List[GPUMetrics], final_metrics: List[GPUMetrics],
                        method: str):
        """Generate monitoring report"""
        # Read all collected data and organize by timestamp
        all_power = []  # Individual GPU power values
        all_temp = []
        all_util = []
        timestamp_data = {}  # timestamp -> list of GPU data
        
        try:
            with open(filename, 'r') as f:
                gpu_ids = set()
                for line in f:
                    data = json.loads(line)
                    gpu_ids.add(data.get('gpu_id', 0))
                    timestamp = data.get('timestamp')
                    
                    if timestamp not in timestamp_data:
                        timestamp_data[timestamp] = []
                    timestamp_data[timestamp].append(data)
                    
                    if data.get('power_watts') is not None:
                        try:
                            all_power.append(float(data['power_watts']))
                        except (ValueError, TypeError):
                            debug_print(f"Invalid power value in file: {data['power_watts']} (type: {type(data['power_watts'])})")
                    if data.get('temperature_celsius') is not None:
                        try:
                            all_temp.append(float(data['temperature_celsius']))
                        except (ValueError, TypeError):
                            debug_print(f"Invalid temperature value in file: {data['temperature_celsius']}")
                    if data.get('utilization_percent') is not None:
                        try:
                            all_util.append(float(data['utilization_percent']))
                        except (ValueError, TypeError):
                            debug_print(f"Invalid utilization value in file: {data['utilization_percent']}")
                
                gpu_count = len(gpu_ids)
                
        except FileNotFoundError:
            debug_print(f"Data file not found: {filename}")
            return
        
        # Calculate total system power per timestamp
        total_power_per_timestamp = []
        for timestamp, gpu_data_list in timestamp_data.items():
            # Ensure all power values are numeric before summing
            numeric_powers = []
            for d in gpu_data_list:
                power_val = d.get('power_watts')
                if power_val is not None:
                    try:
                        numeric_powers.append(float(power_val))
                    except (ValueError, TypeError):
                        debug_print(f"Invalid power value in data: {power_val} (type: {type(power_val)})")
            
            if numeric_powers:  # Only include if we have valid power data
                total_power_per_timestamp.append(sum(numeric_powers))
        
        # Power statistics (individual GPU values and system totals)
        max_individual_gpu_power = max(all_power, default=0)
        min_individual_gpu_power = min(all_power, default=0)
        avg_individual_gpu_power = sum(all_power) / len(all_power) if all_power else 0
        
        max_total_system_power = max(total_power_per_timestamp, default=0)
        min_total_system_power = min(total_power_per_timestamp, default=0)
        avg_total_system_power = sum(total_power_per_timestamp) / len(total_power_per_timestamp) if total_power_per_timestamp else 0
        
        # Calculate statistics
        duration = end_time - start_time
        total_energy_wh = self._calculate_energy_consumption(initial_metrics, final_metrics)
        
        # Calculate expected energy based on average power for validation
        duration_hours = duration.total_seconds() / 3600
        duration_seconds = duration.total_seconds()
        expected_energy_wh = avg_total_system_power * duration_hours if total_power_per_timestamp else 0
        
        # Convert energy to different units
        total_energy_j = total_energy_wh * 3600  # 1 Wh = 3600 J
        avg_power_from_energy = total_energy_wh / duration_hours if duration_hours > 0 else 0
        
        # Generate report
        report = f"""
=== AMD GPU Energy Report ({method.upper()}) ===

Duration: {duration}
Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}
GPUs: {gpu_count}

System Power Statistics:
  Max Total: {max_total_system_power:.1f} W
  Min Total: {min_total_system_power:.1f} W
  Avg Total: {avg_total_system_power:.1f} W

Individual GPU Power Statistics:
  Max Single GPU: {max_individual_gpu_power:.1f} W
  Min Single GPU: {min_individual_gpu_power:.1f} W
  Avg Single GPU: {avg_individual_gpu_power:.1f} W

Temperature Statistics:
  Max: {max(all_temp, default=0):.1f} °C
  Avg: {sum(all_temp)/len(all_temp) if all_temp else 0:.1f} °C

Utilization Statistics:
  Max: {max(all_util, default=0):.1f} %
  Avg: {sum(all_util)/len(all_util) if all_util else 0:.1f} %

Energy Consumption:
  Total Energy: {total_energy_j:.0f} J ({total_energy_wh:.6f} Wh, {total_energy_wh/1000:.9f} kWh)
  Average Power (from energy counter): {avg_power_from_energy:.1f} W
  Expected Power (from sampled power): {avg_total_system_power:.1f} W
  Measurement accuracy: {(total_energy_wh/expected_energy_wh*100) if expected_energy_wh > 0 else 0:.1f}%
  Duration: {duration_seconds:.1f} seconds
  Energy data available: {len(initial_metrics)} GPUs

Energy Counter vs Sampled Power Comparison:
  Energy Counter Method: {total_energy_wh:.6f} Wh ({avg_power_from_energy:.1f} W avg)
  Power Sampling Method: {expected_energy_wh:.6f} Wh ({avg_total_system_power:.1f} W avg)
  Difference: {abs(avg_power_from_energy - avg_total_system_power):.1f} W ({abs(avg_power_from_energy - avg_total_system_power)/avg_total_system_power*100 if avg_total_system_power > 0 else 0:.1f}%)
"""
        
        print(report)
        
        # Save report
        report_filename = os.path.join(self.output_dir, 
                                     f"report_{method}_{end_time.strftime('%Y%m%d_%H%M%S')}.txt")
        with open(report_filename, 'w') as f:
            f.write(report)
        info_print(f"Report saved: {report_filename}")
    
    def monitor(self, use_amdsmi: bool = True, use_rocm_smi: bool = True):
        """Start monitoring GPUs"""
        # Apply environment variable overrides
        use_amdsmi = use_amdsmi and ENABLE_AMDSMI
        use_rocm_smi = use_rocm_smi and ENABLE_ROCM_SMI
        
        if not (self.amdsmi_available or self.rocm_smi_available):
            info_print("No monitoring tools available!")
            return
        
        # Setup monitoring
        methods = []
        if use_amdsmi and self.amdsmi_available:
            methods.append('amdsmi')
        if use_rocm_smi and self.rocm_smi_available:
            methods.append('rocm_smi')
        
        if not methods:
            info_print("No monitoring methods enabled!")
            return
        
        # Initialize data collection
        start_time = datetime.now()
        filenames = {}
        initial_metrics = {}
        
        for method in methods:
            filename = os.path.join(self.output_dir, 
                                  f"gpu_metrics_{method}_{start_time.strftime('%Y%m%d_%H%M%S')}.jsonl")
            filenames[method] = filename
            
            # Get initial metrics for energy calculation
            if method == 'amdsmi':
                initial_metrics[method] = self._get_amdsmi_metrics()
            else:
                initial_metrics[method] = self._get_rocm_smi_metrics()
            
            debug_print(f"Initial {method} metrics: {len(initial_metrics[method])} GPUs")
        
        info_print(f"\nMonitoring started with methods: {', '.join(methods)}")
        info_print("Press Ctrl+C to stop monitoring\n")
        
        try:
            while True:
                for method in methods:
                    if method == 'amdsmi':
                        metrics = self._get_amdsmi_metrics()
                    else:
                        metrics = self._get_rocm_smi_metrics()
                    
                    if metrics:
                        self._save_metrics(metrics, filenames[method])
                        
                        # Print current status
                        valid_power = [m.power_watts for m in metrics if m.power_watts is not None]
                        # Ensure all power values are numeric
                        numeric_power = []
                        for power in valid_power:
                            try:
                                numeric_power.append(float(power))
                            except (ValueError, TypeError):
                                debug_print(f"Invalid power value: {power} (type: {type(power)})")
                        
                        total_power = sum(numeric_power)
                        info_print(f"{method}: {len(metrics)} GPUs, Total Power: {total_power:.1f}W ({len(numeric_power)} with data)")
                
                time.sleep(self.sampling_interval)
                
        except KeyboardInterrupt:
            info_print("\nMonitoring stopped.")
        
        finally:
            end_time = datetime.now()
            
            # Generate reports
            for method in methods:
                if method == 'amdsmi':
                    final_metrics = self._get_amdsmi_metrics()
                else:
                    final_metrics = self._get_rocm_smi_metrics()
                
                self._generate_report(filenames[method], start_time, end_time,
                                    initial_metrics[method], final_metrics, method)

def main():
    """Main function"""
    # Print configuration status
    config_info = []
    if DEBUG_MODE:
        config_info.append("DEBUG mode: ON")
    else:
        config_info.append("DEBUG mode: OFF")
    
    if QUIET_MODE:
        config_info.append("QUIET mode: ON")
    else:
        config_info.append("QUIET mode: OFF")
    
    if ENABLE_AMDSMI:
        config_info.append("AMDSMI: Enabled")
    else:
        config_info.append("AMDSMI: Disabled")
    
    if ENABLE_ROCM_SMI:
        config_info.append("ROCm-SMI: Enabled")
    else:
        config_info.append("ROCm-SMI: Disabled")
    
    config_info.append(f"Sampling interval: {SAMPLING_INTERVAL}s")
    
    if not QUIET_MODE:
        print("=== AMD GPU Monitor Configuration ===")
        for info in config_info:
            print(f"  {info}")
        print("")
        
        # Recommendations based on sampling interval
        if SAMPLING_INTERVAL < 0.5:
            print("WARNING: High frequency sampling may cause significant CPU overhead")
        elif SAMPLING_INTERVAL >= 5.0:
            print("INFO: Low frequency sampling may miss short power spikes")
        
        print("Environment variable options:")
        if not DEBUG_MODE:
            print("   AMD_GPU_MONITOR_DEBUG=true (enable debug messages)")
        if not QUIET_MODE:
            print("   AMD_GPU_MONITOR_QUIET=true (suppress info messages)")
        if ENABLE_AMDSMI:
            print("   AMD_GPU_MONITOR_DISABLE_AMDSMI=true (disable AMDSMI)")
        if ENABLE_ROCM_SMI:
            print("   AMD_GPU_MONITOR_DISABLE_ROCM_SMI=true (disable ROCm-SMI)")
        print(f"   AMD_GPU_MONITOR_INTERVAL=<seconds> (current: {SAMPLING_INTERVAL}s)")
        print("")
    
    monitor = AMDGPUMonitor()
    
    # Monitor with enabled methods
    monitor.monitor(use_amdsmi=ENABLE_AMDSMI, use_rocm_smi=ENABLE_ROCM_SMI)

if __name__ == "__main__":
    main()
