// Execute the unbury.me calculation loop (src/LoanApp.js) headlessly with DOM stubs.
// Does not copy upstream code: it loads the external clone's files at run time.
// Usage:
//   git clone https://github.com/duaneking/unburyme.git /some/dir/unburyme
//   git -C /some/dir/unburyme checkout c4e6119f2ea7575de5144275e4795dea28231b24
//   node unburyme_harness.js /some/dir/unburyme
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const root = process.argv[2];

const ctx = { console, Date };
const stub$ = () => new Proxy(function () {}, { get: () => stub$(), apply: () => stub$() });
ctx.$ = stub$();
ctx.jQuery = ctx.$;
vm.createContext(ctx);
vm.runInContext('var Unburyme = {};', ctx);
for (const f of ['Config.js', 'Date.js', 'LoanApp.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'src', f), 'utf8'), ctx, { filename: f });
}
// Minimal stand-ins for display classes that the calculation calls into.
vm.runInContext(`
Unburyme.Graph = function(){}; Unburyme.Graph.prototype.draw = function(){};
Unburyme.TotalResults = function(){}; Unburyme.TotalResults.prototype.calculate = function(){};
function FakeResults(){ this.rows=[]; this.totalInterestPaid=0; this.payOffDate=new Unburyme.Date(); this.paidMonth=null; }
FakeResults.prototype.drawStart=function(){}; FakeResults.prototype.drawFinal=function(){};
FakeResults.prototype.drawMain=function(it,m,pay,princ,intr,bal){ this.rows.push({it:it,pay:pay,princ:princ,intr:intr,bal:bal}); };
function FakeLoan(uid,b,mp,r){ this.uid=uid; this.b=b; this.mp=mp; this.r=r; this.results=new FakeResults(); }
FakeLoan.prototype.getName=function(){return 'L'+this.uid;};
FakeLoan.prototype.getBalance=function(){return this.b;};
FakeLoan.prototype.getMinPayment=function(){return this.mp;};
FakeLoan.prototype.getInterest=function(){return this.r;};
FakeLoan.prototype.getUID=function(){return this.uid;};
function runCase(loans, total, type){
  var app = new Unburyme.LoanApp();
  app.paymentType = type;
  app.loanArray = loans; app.initLoanArray = loans; app.loanCount = loans.length;
  app.initLoanCount = function(){ return loans.length; };
  app.areLoansValid = function(){ return true; };
  app.totalPayment = total; app.validPayment = true;
  app.totalMinPayment = loans.reduce(function(s,l){return s+l.mp;},0);
  app.impossibleCalcDisplay = function(){};
  var sorted = app.sortLoans();
  app.possibleCalc = true;
  app.calculate(sorted);
  return {app: app, sorted: sorted};
}
`, ctx);

function report(name, cond, detail) {
  console.log(`[${cond ? 'REPRODUCED' : 'NOT REPRODUCED'}] ${name}: ${detail}`);
}

// U1: zero-APR loan breaks the selection sort (strict > against 0 picks uid 0 repeatedly)
{
  const r = vm.runInContext(`runCase([new FakeLoan(0,1000,50,20), new FakeLoan(1,500,25,0)], 200, 'avalanche')`, ctx);
  const ids = r.sorted.map(l => l.uid);
  report('U1 zero-APR loan dropped from ordering', new Set(ids).size < ids.length,
    `avalanche order uids = [${ids}] (loan 1 at 0% missing, loan 0 duplicated)`);
}

// U2: second distribution pass re-applies the whole monthly payment to unpaid loans
{
  const r = vm.runInContext(`runCase([new FakeLoan(0,100,25,20), new FakeLoan(1,5000,100,10)], 500, 'avalanche')`, ctx);
  const big = r.sorted.find(l => l.uid === 1).results.rows[0];
  const expectedEnd = 5000 + 5000 * 0.10 / 12 - (500 - (100 + 100 * 0.2 / 12));
  report('U2 double-applied principal after a payoff', Math.abs(big.bal - expectedEnd) > 0.01,
    `month-1 balance of loan 1: upstream ${big.bal.toFixed(2)}, conservation implies ${expectedEnd.toFixed(2)}`);
}

// U3: ordering is computed once, not re-ranked monthly
{
  const src = fs.readFileSync(path.join(root, 'src', 'LoanApp.js'), 'utf8');
  report('U3 static ordering (static check)', /var sortedLoans = this\.sortLoans\(\);/.test(src) &&
    !/sortLoans\(\)[\s\S]*while\(remainingLoans/.test(src.slice(src.indexOf('prototype.calculate ='))),
    'sortLoans() is called once in calculatePrep(); calculate() never re-sorts');
}
