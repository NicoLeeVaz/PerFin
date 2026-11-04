"""Probe bryankemp/financial-debt-optimizer @ 16b6691bce77f036a81625c9f9b02995cb4129a9 (external clone).

    /some/venv/bin/python fdo_probe.py /some/dir/financial-debt-optimizer
Requires its requirements.txt dependencies in that venv. No upstream code is copied.
"""
import sys
from datetime import date

sys.path.insert(0, sys.argv[1])
from debt_optimizer.core.financial_calc import Debt, Income  # noqa: E402
from debt_optimizer.core.debt_optimizer import DebtOptimizer, PaymentStrategy  # noqa: E402


def report(name, cond, detail):
    print(f"[{'REPRODUCED' if cond else 'NOT REPRODUCED'}] {name}: {detail}")


# F1: minimum payment below monthly interest -> is unpaid interest capitalised?
debts = [Debt("CARD", 5000.0, 20.0, 25.0, 15)]
inc = [Income("job", 20.0, "monthly", date.today())]
opt = DebtOptimizer(debts, inc, settings={"current_bank_balance": 0.0})
res = opt._run_payment_simulation(debts, 0.0)
sched = res["payment_schedule"]  # pandas DataFrame
pays = sched[sched["type"] == "payment"].head(12)
interest_charged = 5000.0 * 0.25 / 12
end_bal = float(pays["remaining_balance"].iloc[-1]) if len(pays) else None
print("payments observed:", len(pays), "amounts:", sorted(set(pays["amount"].round(2))),
      "interest portions:", sorted(set(pays["interest_portion"].round(2))))
report("F1 unpaid interest not capitalised", end_bal is not None and end_bal <= 5000.0,
       f"12 payments of $20 vs ~${interest_charged:.2f}/month interest; reported balance after them = {end_bal}")

# F2: run is anchored to the wall clock
report("F2 wall-clock dependence (static)", True,
       "_run_payment_simulation uses start_date = date.today(); same inputs on different days give different schedules")
