import os, signal, time, subprocess

result = subprocess.run(['pgrep', '-f', 'python3.*main.py'], capture_output=True, text=True)
pids = [p for p in result.stdout.strip().split('\n') if p]
print("Found PIDs:", pids)

for pid in pids:
    try:
        os.kill(int(pid), signal.SIGTERM)
        print(f"Sent SIGTERM to {pid}")
    except Exception as e:
        print(f"Error killing {pid}: {e}")

time.sleep(3)

p = subprocess.Popen(
    ['python3', 'main.py'],
    stdout=open('/home/tracy/discord-bot/bot.log', 'w'),
    stderr=subprocess.STDOUT,
    cwd='/home/tracy/discord-bot'
)
print("New PID:", p.pid)
