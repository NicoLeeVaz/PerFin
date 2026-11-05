"""Small offline launcher; operations use the same validated CLI as automation."""
import subprocess
import sys


def launch(data_root, acknowledge=False, backend='sqlite'):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root=tk.Tk();root.title('PerFin — Local Finance');root.geometry('1000x760')
    ttk.Label(root,text='Data stays in '+str(data_root)+' ('+backend+')').pack(anchor='w',padx=12,pady=8)
    form=ttk.Frame(root);form.pack(fill='x',padx=12)
    fields={}
    defaults={'Account':'chk:main','Profile':'synthetic_checking_signed','CSV file':'','Batch':'','Approve rows':'','Reject rows':'','Reason':'',
              'From transaction':'','To transaction':''}
    for i,(label,default) in enumerate(defaults.items()):
        ttk.Label(form,text=label).grid(row=i,column=0,sticky='w');v=tk.StringVar(value=default);fields[label]=v
        ttk.Entry(form,textvariable=v,width=100).grid(row=i,column=1,sticky='ew',padx=5,pady=2)
    def browse():fields['CSV file'].set(filedialog.askopenfilename(filetypes=[('CSV','*.csv'),('All files','*')]))
    ttk.Button(form,text='Browse CSV',command=browse).grid(row=2,column=2)
    output=tk.Text(root,wrap='none',height=23);output.pack(fill='both',expand=True,padx=12,pady=10)
    def run(args,confirm=False):
        if confirm and not messagebox.askyesno('Confirm local change','Apply this explicit action to the local '+backend+' database?'):return
        command=[sys.executable,'-m','perfin_app','--data-root',str(data_root),'--backend',backend]
        if acknowledge:command+=['--acknowledge-location']
        root.config(cursor='watch');root.update_idletasks()
        try:
            p=subprocess.run(command+args,capture_output=True,text=True,check=False)
            output.delete('1.0','end');output.insert('end',p.stdout+p.stderr)
            if args[0]=='import' and p.returncode==0:
                import json
                fields['Batch'].set(json.loads(p.stdout)['document']['batch']['batch_id'])
        finally:root.config(cursor='')
    def review():
        args=['review',fields['Batch'].get()]
        for key,flag in [('Approve rows','--approve'),('Reject rows','--reject'),('Reason','--reason')]:
            if fields[key].get():args += [flag,fields[key].get()]
        run(args,True)
    bar=ttk.Frame(root);bar.pack(fill='x',padx=12,pady=8)
    actions=[('Initialize',lambda:run(['init'],True)),('Status',lambda:run(['status'])),
             ('Stage CSV',lambda:run(['import',fields['CSV file'].get(),'--account',fields['Account'].get(),'--profile',fields['Profile'].get()])),
             ('Preview',lambda:run(['preview',fields['Batch'].get()])),('Review selected rows',review),
             ('Commit approved',lambda:run(['commit',fields['Batch'].get()],True)),
             ('Link payment',lambda:run(['link-transfer',fields['From transaction'].get(),fields['To transaction'].get()],True)),
             ('Refresh Excel',lambda:run(['refresh'])),('Backup',lambda:run(['backup']))]
    for label,action in actions:ttk.Button(bar,text=label,command=action).pack(side='left',padx=2)
    root.mainloop()
