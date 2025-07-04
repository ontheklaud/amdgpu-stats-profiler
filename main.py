#!/usr/bin/env python3
"""
Semi-Structured ROCm-SMI GPU Monitor
"""

import subprocess
import json
import time
import sys
from datetime import datetime

# Simple configuration
DEBUG = False
INTERVAL = 2.0

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

def get_gpu_data():
    """Get GPU data from rocm-smi"""
    try:
        result = subprocess.run(['rocm-smi', '--showall', '--json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            debug_print(f"rocm-smi failed: {result.stderr}")
            return None
        
        return json.loads(result.stdout)
    except Exception as e:
        debug_print(f"Error getting GPU data: {e}")
        return None

def parse_gpu_metrics(data):
    """Parse GPU metrics from rocm-smi data"""
    if not data:
        return []
    
    gpu_list = []
    timestamp = datetime.now().isoformat()
    
    for card_key, gpu_data in data.items():
        if not card_key.startswith('card'):
            continue
            
        gpu_id = int(card_key.replace('card', ''))
        
        # Extract metrics
        gpu_info = {
            'gpu_id': gpu_id,
            'timestamp': timestamp,
            'power': safe_float(gpu_data.get('Current Socket Graphics Package Power (W)')),
            'temp': safe_float(gpu_data.get('Temperature (Sensor junction) (C)')),
            'util': safe_float(gpu_data.get('GPU use (%)')),
            'vram': safe_float(gpu_data.get('GPU Memory Allocated (VRAM%)')),
            'sclk': safe_float(gpu_data.get('current_gfxclk (MHz)')),
            'mclk': safe_float(gpu_data.get('current_uclk (MHz)')),
        }
        
        # Try to get energy counter
        energy_counter = gpu_data.get('energy_accumulator') or gpu_data.get('Energy counter')
        if energy_counter:
            try:
                gpu_info['energy'] = int(energy_counter)
            except:
                gpu_info['energy'] = None
        else:
            gpu_info['energy'] = None
        
        gpu_list.append(gpu_info)
        debug_print(f"GPU {gpu_id}: {gpu_info['power']}W, {gpu_info['temp']}°C")
    
    return gpu_list

def print_gpu_status(gpu_list):
    """Print current GPU status"""
    if not gpu_list:
        print("No GPU data available")
        return
    
    print(f"\n=== GPU Status - {datetime.now().strftime('%H:%M:%S')} ===")
    for gpu in gpu_list:
        power = f"{gpu['power']:.1f}W" if gpu['power'] else "N/A"
        temp = f"{gpu['temp']:.1f}°C" if gpu['temp'] else "N/A"
        util = f"{gpu['util']:.1f}%" if gpu['util'] else "N/A"
        vram = f"{gpu['vram']:.1f}%" if gpu['vram'] else "N/A"
        
        print(f"GPU {gpu['gpu_id']}: {power}, {temp}, {util} util, {vram} VRAM")

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
    for gpu in gpu_list:
        if gpu['power'] is not None:
            total += gpu['power']
            count += 1
    return total, count

def simple_stats(filename):
    """Calculate simple statistics from saved data"""
    try:
        with open(filename, 'r') as f:
            powers = []
            temps = []
            utils = []
            
            for line in f:
                data = json.loads(line)
                if data.get('power') is not None:
                    powers.append(data['power'])
                if data.get('temp') is not None:
                    temps.append(data['temp'])
                if data.get('util') is not None:
                    utils.append(data['util'])
        
        print(f"\n=== Simple Statistics ===")
        if powers:
            print(f"Power: Avg={sum(powers)/len(powers):.1f}W, Max={max(powers):.1f}W")
        if temps:
            print(f"Temperature: Avg={sum(temps)/len(temps):.1f}°C, Max={max(temps):.1f}°C")
        if utils:
            print(f"Utilization: Avg={sum(utils)/len(utils):.1f}%, Max={max(utils):.1f}%")
        
    except Exception as e:
        debug_print(f"Error calculating stats: {e}")

def monitor_once():
    """Single measurement"""
    data = get_gpu_data()
    gpu_list = parse_gpu_metrics(data)
    print_gpu_status(gpu_list)
    
    total_power, gpu_count = calculate_total_power(gpu_list)
    if gpu_count > 0:
        print(f"Total System Power: {total_power:.1f}W ({gpu_count} GPUs)")

def monitor_loop(save_data=False):
    """Monitoring loop"""
    print(f"ROCm-SMI Monitor - Interval: {INTERVAL}s")
    print("Press Ctrl+C to stop\n")
    
    filename = None
    if save_data:
        filename = f"gpu_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        print(f"Saving data to: {filename}")
    
    try:
        while True:
            data = get_gpu_data()
            gpu_list = parse_gpu_metrics(data)
            
            if gpu_list:
                print_gpu_status(gpu_list)
                
                total_power, gpu_count = calculate_total_power(gpu_list)
                if gpu_count > 0:
                    print(f"Total: {total_power:.1f}W ({gpu_count} GPUs)")
                
                if save_data and filename:
                    save_to_file(gpu_list, filename)
            
            time.sleep(INTERVAL)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        
        if save_data and filename:
            simple_stats(filename)

def check_rocm_smi():
    """Check if rocm-smi is available"""
    try:
        result = subprocess.run(['rocm-smi', '--version'], 
                              capture_output=True, timeout=3)
        return result.returncode == 0
    except:
        return False

def main():
    """Main function"""
    global DEBUG, INTERVAL
    
    # Simple argument parsing
    if '--debug' in sys.argv:
        DEBUG = True
    if '--fast' in sys.argv:
        INTERVAL = 0.5
    if '--slow' in sys.argv:
        INTERVAL = 5.0
    
    print("=== ROCm-SMI GPU Monitor (Semi-Structured) ===")
    if DEBUG:
        print("Debug mode: ON")
    print(f"Sampling interval: {INTERVAL}s\n")
    
    # Check rocm-smi availability
    if not check_rocm_smi():
        print("Error: rocm-smi not found or not working")
        sys.exit(1)
    
    # Handle different modes
    if '--once' in sys.argv:
        monitor_once()
    elif '--save' in sys.argv:
        monitor_loop(save_data=True)
    else:
        monitor_loop(save_data=False)

if __name__ == "__main__":
    main()