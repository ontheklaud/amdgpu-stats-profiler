#!/usr/bin/env python3
"""
Semi-Structured GPU Monitor with Dual API
Functions for both ROCm-SMI and AMD SMI
"""

import subprocess
import json
import time
import sys
from datetime import datetime

# Simple configuration
DEBUG = False
INTERVAL = 2.0
USE_AMDSMI = True
USE_ROCMSMI = True

def debug_print(msg):
    """Print debug message if enabled"""
    if DEBUG:
        print(f"DEBUG: {msg}")

def safe_float(value):
    """Convert value to float safely"""
    if value is None or value == 'N/A':
        return None
    try:
        return float(value)
    except:
        return None

def safe_int(value):
    """Convert value to int safely"""
    if value is None or value == 'N/A':
        return None
    try:
        return int(value)
    except:
        return None

def check_amdsmi():
    """Check if AMD SMI is available"""
    try:
        import amdsmi
        amdsmi.amdsmi_init()
        handles = amdsmi.amdsmi_get_processor_handles()
        amdsmi.amdsmi_shut_down()
        return len(handles) > 0
    except Exception as e:
        debug_print(f"AMD SMI not available: {e}")
        return False

def check_rocmsmi():
    """Check if ROCm-SMI is available"""
    try:
        result = subprocess.run(['rocm-smi', '--version'], 
                              capture_output=True, timeout=3)
        return result.returncode == 0
    except:
        return False

def get_amdsmi_data():
    """Get GPU data from AMD SMI"""
    try:
        import amdsmi
        amdsmi.amdsmi_init()
        
        handles = amdsmi.amdsmi_get_processor_handles()
        gpu_list = []
        timestamp = datetime.now().isoformat()
        
        for i, handle in enumerate(handles):
            gpu_info = {
                'gpu_id': i,
                'timestamp': timestamp,
                'method': 'amdsmi'
            }
            
            # Try to get comprehensive metrics first
            try:
                metrics = amdsmi.amdsmi_get_gpu_metrics_info(handle)
                debug_print(f"AMD SMI GPU {i}: Got comprehensive metrics")
                
                # Extract data from comprehensive metrics
                gpu_info['power'] = safe_float(metrics.get('average_socket_power') or 
                                             metrics.get('current_socket_power'))
                gpu_info['temp'] = safe_float(metrics.get('temperature_edge') or 
                                            metrics.get('temperature_hotspot'))
                gpu_info['util'] = safe_float(metrics.get('average_gfx_activity'))
                gpu_info['sclk'] = safe_float(metrics.get('average_gfxclk_frequency') or 
                                            metrics.get('current_gfxclk'))
                gpu_info['mclk'] = safe_float(metrics.get('average_uclk_frequency') or 
                                            metrics.get('current_uclk'))
                gpu_info['energy'] = safe_int(metrics.get('energy_accumulator'))
                
            except Exception as e:
                debug_print(f"AMD SMI GPU {i}: Comprehensive metrics failed: {e}")
                
                # Fallback to individual API calls
                try:
                    power_info = amdsmi.amdsmi_get_power_info(handle)
                    gpu_info['power'] = safe_float(power_info.get('current_socket_power') or 
                                                 power_info.get('average_socket_power'))
                except:
                    gpu_info['power'] = None
                
                try:
                    from amdsmi import AmdSmiTemperatureType, AmdSmiTemperatureMetric
                    temp_result = amdsmi.amdsmi_get_temp_metric(handle, 
                                                              AmdSmiTemperatureType.EDGE, 
                                                              AmdSmiTemperatureMetric.CURRENT)
                    gpu_info['temp'] = safe_float(temp_result / 1000.0) if temp_result else None
                except:
                    gpu_info['temp'] = None
                
                try:
                    activity = amdsmi.amdsmi_get_gpu_activity(handle)
                    gpu_info['util'] = safe_float(activity.get('gfx_activity'))
                except:
                    gpu_info['util'] = None
                
                try:
                    energy = amdsmi.amdsmi_get_energy_count(handle)
                    gpu_info['energy'] = safe_int(energy.get('energy_accumulator') or 
                                                energy.get('power') or 
                                                energy.get('counter'))
                except:
                    gpu_info['energy'] = None
                
                gpu_info['sclk'] = None
                gpu_info['mclk'] = None
            
            # VRAM usage (separate API call)
            try:
                vram = amdsmi.amdsmi_get_gpu_vram_usage(handle)
                vram_used = vram.get('vram_used', 0)
                vram_total = vram.get('vram_total', 1)
                gpu_info['vram'] = (vram_used / vram_total) * 100 if vram_total > 0 else None
            except:
                gpu_info['vram'] = None
            
            gpu_list.append(gpu_info)
            debug_print(f"AMD SMI GPU {i}: {gpu_info['power']}W, {gpu_info['temp']}°C")
        
        amdsmi.amdsmi_shut_down()
        return gpu_list
        
    except Exception as e:
        debug_print(f"AMD SMI error: {e}")
        try:
            import amdsmi
            amdsmi.amdsmi_shut_down()
        except:
            pass
        return []

def get_rocmsmi_data():
    """Get GPU data from ROCm-SMI"""
    try:
        result = subprocess.run(['rocm-smi', '--showall', '--json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            debug_print(f"ROCm-SMI failed: {result.stderr}")
            return []
        
        data = json.loads(result.stdout)
        gpu_list = []
        timestamp = datetime.now().isoformat()
        
        for card_key, gpu_data in data.items():
            if not card_key.startswith('card'):
                continue
                
            gpu_id = int(card_key.replace('card', ''))
            
            gpu_info = {
                'gpu_id': gpu_id,
                'timestamp': timestamp,
                'method': 'rocmsmi',
                'power': safe_float(gpu_data.get('Current Socket Graphics Package Power (W)')),
                'temp': safe_float(gpu_data.get('Temperature (Sensor junction) (C)')),
                'util': safe_float(gpu_data.get('GPU use (%)')),
                'vram': safe_float(gpu_data.get('GPU Memory Allocated (VRAM%)')),
                'sclk': safe_float(gpu_data.get('current_gfxclk (MHz)')),
                'mclk': safe_float(gpu_data.get('current_uclk (MHz)')),
            }
            
            # Try to get energy counter
            energy_counter = gpu_data.get('energy_accumulator') or gpu_data.get('Energy counter')
            gpu_info['energy'] = safe_int(energy_counter) if energy_counter else None
            
            gpu_list.append(gpu_info)
            debug_print(f"ROCm-SMI GPU {gpu_id}: {gpu_info['power']}W, {gpu_info['temp']}°C")
        
        return gpu_list
        
    except Exception as e:
        debug_print(f"ROCm-SMI error: {e}")
        return []

def get_gpu_data():
    """Get GPU data from available APIs"""
    all_data = []
    
    if USE_AMDSMI and check_amdsmi():
        amdsmi_data = get_amdsmi_data()
        all_data.extend(amdsmi_data)
    
    if USE_ROCMSMI and check_rocmsmi():
        rocmsmi_data = get_rocmsmi_data()
        # Only add ROCm-SMI data if we don't have AMD SMI data
        if not all_data:
            all_data.extend(rocmsmi_data)
    
    return all_data

def print_gpu_status(gpu_list):
    """Print current GPU status"""
    if not gpu_list:
        print("No GPU data available")
        return
    
    print(f"\n=== GPU Status - {datetime.now().strftime('%H:%M:%S')} ===")
    
    # Group by method
    methods = {}
    for gpu in gpu_list:
        method = gpu.get('method', 'unknown')
        if method not in methods:
            methods[method] = []
        methods[method].append(gpu)
    
    for method, gpus in methods.items():
        print(f"\n[{method.upper()}]")
        for gpu in gpus:
            power = f"{gpu['power']:.1f}W" if gpu['power'] else "N/A"
            temp = f"{gpu['temp']:.1f}°C" if gpu['temp'] else "N/A"
            util = f"{gpu['util']:.1f}%" if gpu['util'] else "N/A"
            vram = f"{gpu['vram']:.1f}%" if gpu['vram'] else "N/A"
            
            print(f"  GPU {gpu['gpu_id']}: {power}, {temp}, {util} util, {vram} VRAM")

def save_to_file(gpu_list, filename):
    """Save GPU data to file"""
    try:
        with open(filename, 'a') as f:
            for gpu in gpu_list:
                f.write(json.dumps(gpu) + '\n')
        debug_print(f"Saved {len(gpu_list)} GPU records to {filename}")
    except Exception as e:
        debug_print(f"Error saving to file: {e}")

def calculate_total_power(gpu_list):
    """Calculate total system power"""
    total = 0
    count = 0
    methods = set()
    
    for gpu in gpu_list:
        if gpu['power'] is not None:
            total += gpu['power']
            count += 1
            methods.add(gpu.get('method', 'unknown'))
    
    return total, count, methods

def simple_stats(filename):
    """Calculate simple statistics from saved data"""
    try:
        with open(filename, 'r') as f:
            data_by_method = {}
            
            for line in f:
                data = json.loads(line)
                method = data.get('method', 'unknown')
                
                if method not in data_by_method:
                    data_by_method[method] = {'powers': [], 'temps': [], 'utils': []}
                
                if data.get('power') is not None:
                    data_by_method[method]['powers'].append(data['power'])
                if data.get('temp') is not None:
                    data_by_method[method]['temps'].append(data['temp'])
                if data.get('util') is not None:
                    data_by_method[method]['utils'].append(data['util'])
        
        print(f"\n=== Statistics by Method ===")
        for method, stats in data_by_method.items():
            print(f"\n[{method.upper()}]")
            
            if stats['powers']:
                powers = stats['powers']
                print(f"  Power: Avg={sum(powers)/len(powers):.1f}W, Max={max(powers):.1f}W")
            
            if stats['temps']:
                temps = stats['temps']
                print(f"  Temperature: Avg={sum(temps)/len(temps):.1f}°C, Max={max(temps):.1f}°C")
            
            if stats['utils']:
                utils = stats['utils']
                print(f"  Utilization: Avg={sum(utils)/len(utils):.1f}%, Max={max(utils):.1f}%")
        
    except Exception as e:
        debug_print(f"Error calculating stats: {e}")

def monitor_once():
    """Single measurement"""
    gpu_list = get_gpu_data()
    print_gpu_status(gpu_list)
    
    total_power, gpu_count, methods = calculate_total_power(gpu_list)
    if gpu_count > 0:
        methods_str = ", ".join(methods)
        print(f"\nTotal System Power: {total_power:.1f}W ({gpu_count} GPUs via {methods_str})")

def monitor_loop(save_data=False):
    """Monitoring loop"""
    methods = []
    if USE_AMDSMI and check_amdsmi():
        methods.append("AMD SMI")
    if USE_ROCMSMI and check_rocmsmi():
        methods.append("ROCm-SMI")
    
    if not methods:
        print("No monitoring APIs available!")
        return
    
    print(f"Dual API Monitor - Methods: {', '.join(methods)}")
    print(f"Interval: {INTERVAL}s")
    print("Press Ctrl+C to stop\n")
    
    filename = None
    if save_data:
        filename = f"gpu_data_dual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        print(f"Saving data to: {filename}")
    
    try:
        while True:
            gpu_list = get_gpu_data()
            
            if gpu_list:
                print_gpu_status(gpu_list)
                
                total_power, gpu_count, api_methods = calculate_total_power(gpu_list)
                if gpu_count > 0:
                    methods_str = ", ".join(api_methods)
                    print(f"Total: {total_power:.1f}W ({gpu_count} GPUs via {methods_str})")
                
                if save_data and filename:
                    save_to_file(gpu_list, filename)
            
            time.sleep(INTERVAL)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        
        if save_data and filename:
            simple_stats(filename)

def main():
    """Main function"""
    global DEBUG, INTERVAL, USE_AMDSMI, USE_ROCMSMI
    
    # Simple argument parsing
    if '--debug' in sys.argv:
        DEBUG = True
    if '--fast' in sys.argv:
        INTERVAL = 0.5
    if '--slow' in sys.argv:
        INTERVAL = 5.0
    if '--amdsmi-only' in sys.argv:
        USE_AMDSMI = True
        USE_ROCMSMI = False
    if '--rocmsmi-only' in sys.argv:
        USE_AMDSMI = False
        USE_ROCMSMI = True
    
    print("=== Dual API GPU Monitor (B.5 + AMD SMI) ===")
    print(f"AMD SMI: {'Enabled' if USE_AMDSMI else 'Disabled'}")
    print(f"ROCm-SMI: {'Enabled' if USE_ROCMSMI else 'Disabled'}")
    if DEBUG:
        print("Debug mode: ON")
    print(f"Sampling interval: {INTERVAL}s\n")
    
    # Check API availability
    amdsmi_ok = check_amdsmi() if USE_AMDSMI else False
    rocmsmi_ok = check_rocmsmi() if USE_ROCMSMI else False
    
    if not amdsmi_ok and not rocmsmi_ok:
        print("Error: No monitoring APIs available")
        sys.exit(1)
    
    if USE_AMDSMI and not amdsmi_ok:
        print("Warning: AMD SMI not available, falling back to ROCm-SMI")
    if USE_ROCMSMI and not rocmsmi_ok:
        print("Warning: ROCm-SMI not available")
    
    # Handle different modes
    if '--once' in sys.argv:
        monitor_once()
    elif '--save' in sys.argv:
        monitor_loop(save_data=True)
    else:
        monitor_loop(save_data=False)

if __name__ == "__main__":
    main()