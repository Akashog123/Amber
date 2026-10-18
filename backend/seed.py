"""Mock record system: a procurement log and an equipment list. Run: uv run python seed.py"""
import db

RECORDS = [
    # id, kind, name, aliases, status, owner, details
    ("PO-1041", "procurement", "Centrifugal pump Grundfos CR-32", "main pump, pump order, CR-32",
     "Awaiting vendor quote", "Rahul", "Qty 2. Replacement for Line 3 cooling loop. Budget INR 4.2L."),
    # Second pump item on purpose: forces the confidence check when someone just says "the pump".
    ("PO-1042", "procurement", "Pump mechanical seal kit", "pump seals, seal kit",
     "Ordered, ETA 24 Oct", "Priya", "Qty 10. Vendor: FlowServe India. PO raised 2 Oct."),
    ("PO-1043", "procurement", "Chiller compressor service contract", "chiller service, AMC",
     "Contract under review", "Ankit", "Annual maintenance for Chiller #2. Renewal due 1 Nov."),
    ("PO-1044", "procurement", "VFD drives 15kW", "VFDs, variable frequency drives, drives",
     "Delivered", "Rahul", "Qty 4. Delivered 10 Oct, installation pending."),
    ("PO-1045", "procurement", "PPE kits", "safety kits, PPE",
     "Approved, not ordered", "Sneha", "Qty 50. Approved in last week's sync."),
    # A second Grundfos pump: "the Grundfos pump" is genuinely ambiguous, so Amber has to confirm before writing.
    ("PO-1046", "procurement", "Booster pump Grundfos CM-5", "booster pump, CM-5, Grundfos booster",
     "Ordered, ETA 30 Oct", "Priya", "Qty 1. Pressure booster for the admin block. PO raised 8 Oct."),
    ("EQ-201", "equipment", "Chiller #2", "chiller, chiller two",
     "Running, high vibration flagged", "Ankit", "Carrier 30XA. Last serviced 12 Apr."),
    ("EQ-202", "equipment", "Boiler B1", "boiler",
     "Operational", "Priya", "Thermax 2TPH. Next inspection 15 Dec."),
    ("EQ-203", "equipment", "Cooling tower CT-1", "cooling tower",
     "Fan motor replaced", "Ankit", "Fan motor replaced 3 Oct."),
    ("EQ-204", "equipment", "Air compressor AC-2", "compressor, air compressor",
     "Down for maintenance", "Sneha", "Atlas Copco GA30. Waiting on filter kit."),
]


def seed():
    db.init()
    with db.db() as c:
        # IGNORE, not REPLACE: runs on every start, and must not undo operator edits or statuses Amber set.
        c.executemany("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?,?)", RECORDS)


if __name__ == "__main__":
    seed()
    print(f"seeded {len(RECORDS)} records into {db.DB_PATH}")
