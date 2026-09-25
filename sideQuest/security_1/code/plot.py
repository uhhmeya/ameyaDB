import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

data = np.genfromtxt("latencies.csv", delimiter=",", names=True)
series = {"L1": data["L1"], "L2": data["L2"], "L3": data["L3"], "DRAM": data["DRAM"]}

# ignore outliers
for name, arr in series.items():
    print(f"{name:5s} median={np.median(arr):6.0f}  "
          f"p10={np.percentile(arr,10):6.0f}  p90={np.percentile(arr,90):6.0f}")

XMAX = 320
bins = np.arange(0, XMAX + 2, 2)

plt.figure(figsize=(10, 6))
for name, arr in series.items():
    plt.hist(arr[arr <= XMAX], bins=bins, alpha=0.6, label=name)
plt.xlabel("Access Time")
plt.ylabel("Number of Samples")
plt.legend()
plt.tight_layout()
plt.savefig("latency_hist.png", dpi=150)
print("saved latency_hist.png")