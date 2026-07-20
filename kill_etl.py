import psutil

for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = proc.info.get('cmdline')
        if cmdline and 'python' in proc.info['name'].lower() and 'raw_data_etl.py' in ' '.join(cmdline):
            print(f"Killing PID {proc.info['pid']}")
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
