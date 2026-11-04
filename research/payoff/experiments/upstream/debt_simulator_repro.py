"""Reproduce suspected defects in tomithy83/debt-simulator WITHOUT copying its code.

Usage (upstream clone kept OUTSIDE this repository):
    git clone https://github.com/tomithy83/debt-simulator.git /some/dir/debt-simulator
    git -C /some/dir/debt-simulator checkout 3c03137cde51d82bd15628cadcb59a29ba79888b
    python3 -m venv /some/venv && /some/venv/bin/pip install pandas==2.2.3 python-dateutil==2.9.0.post0
    /some/venv/bin/python debt_simulator_repro.py /some/dir/debt-simulator

Each check prints REPRODUCED or NOT REPRODUCED with the observed numbers.
"""
import sys

up = sys.argv[1]
sys.path.insert(0, up)
import pandas as pd  # noqa: E402
import simulator  # noqa: E402  (upstream module, imported from the external clone)
import strategies  # noqa: E402


def df(rows):
    return pd.DataFrame(rows)


def run(rows, strat, extra, months):
    return pd.DataFrame(simulator.simulate_repayment(df(rows), strat, extra, months))


def report(name, cond, detail):
    print(f"[{'REPRODUCED' if cond else 'NOT REPRODUCED'}] {name}: {detail}")


# R1: split_50_50 overwrites when one card is both highest-rate and lowest-balance
rows = [{"Loan": "ONLY", "Rate": 20.0, "Balance": 5000.0, "MinPayment": 100.0}]
s = run(rows, strategies.split_50_50_strategy, 200.0, 1)
paid = s["Monthly Payment"].sum()
report("R1 50/50 dictionary overwrite", paid < 300.0 - 0.001,
       f"min 100 + extra 200 should pay 300.00; upstream paid {paid:.2f}")

# R2: unused minimum capacity in the payoff month is not spilled to other loans
rows = [{"Loan": "SMALL", "Rate": 12.0, "Balance": 50.0, "MinPayment": 100.0},
        {"Loan": "BIG", "Rate": 20.0, "Balance": 5000.0, "MinPayment": 100.0}]
s = run(rows, strategies.avalanche_strategy, 0.0, 1)
paid = s["Monthly Payment"].sum()
report("R2 payoff-month capacity lost", paid < 200.0 - 0.001,
       f"budget = 200.00 of minimums; month-1 total paid {paid:.2f} (SMALL needed only ~50.50)")

# R3: horizon truncation reported as a payoff month / total months
rows = [{"Loan": "CARD", "Rate": 24.0, "Balance": 10000.0, "MinPayment": 250.0}]
s = run(rows, strategies.avalanche_strategy, 0.0, 6)
summary = simulator.generate_strategy_summary(df(rows), s)
end = s["Ending Balance"].iloc[-1]
pm = summary["Payoff Month"].iloc[0]
report("R3 false payoff at horizon", end > 0 and pm is not None,
       f"ending balance {end:.2f} after 6 months but summary 'Payoff Month' = {pm!r}")

# R4: residual balance <= $0.01 is forgiven (set to zero) without a payment
rows = [{"Loan": "CARD", "Rate": 0.0, "Balance": 100.009, "MinPayment": 100.0}]
s = run(rows, strategies.avalanche_strategy, 0.0, 3)
paid = s["Monthly Payment"].sum()
report("R4 sub-cent/one-cent forgiveness", abs(paid - 100.009) > 1e-9 and s["Ending Balance"].iloc[-1] == 0,
       f"balance 100.009 marked paid after paying {paid:.4f}; money is not integer cents")

# R5: proportional strategy does not re-allocate a capped share
rows = [{"Loan": "TINY", "Rate": 30.0, "Balance": 10.0, "MinPayment": 5.0},
        {"Loan": "BIG", "Rate": 10.0, "Balance": 5000.0, "MinPayment": 50.0}]
s = run(rows, strategies.proportional_interest_strategy, 300.0, 1)
paid = s["Monthly Payment"].sum()
report("R5 proportional leftover dropped", paid < 355.0 - 0.001,
       f"min 55 + extra 300 = 355.00 available; month-1 paid {paid:.2f}")

# R6: negative amortization is simulated silently to the horizon
rows = [{"Loan": "CARD", "Rate": 25.0, "Balance": 5000.0, "MinPayment": 20.0}]
s = run(rows, strategies.avalanche_strategy, 0.0, 12)
end = s["Ending Balance"].iloc[-1]
report("R6 negative amortization not flagged", end > 5000.0,
       f"balance grows 5000.00 -> {end:.2f}; no infeasibility/flag field exists in the output")

# R7: float conservation drift (opening + interest - payment vs ending)
rows = [{"Loan": "A", "Rate": 19.99, "Balance": 3333.33, "MinPayment": 77.77},
        {"Loan": "B", "Rate": 23.49, "Balance": 1111.11, "MinPayment": 33.33}]
raw = simulator.simulate_repayment(df(rows), strategies.avalanche_strategy, 123.45, 600)
s = pd.DataFrame(raw)
drift = (s["Starting Balance"] + s["Interest Paid"] - s["Monthly Payment"] - s["Ending Balance"]).abs().max()
report("R7 rounded report rows do not reconcile", drift > 0.0,
       f"max |start + interest - payment - end| over printed rows = {drift:.4f} (float + display rounding)")
