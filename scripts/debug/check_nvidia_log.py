log_path = r"C:\Users\REDX420\.gemini\antigravity\brain\e88420cc-43ed-476a-a94c-c3a626a41c6c\.system_generated\tasks\task-1532.log"
with open(log_path, "rb") as f:
    text = f.read().decode("utf-8", "ignore")

out_lines = []
for line in text.splitlines():
    if "NVIDIA" in line or "Nemotron" in line:
        out_lines.append(line.encode("ascii", "replace").decode("ascii"))

print("\n".join(out_lines))
