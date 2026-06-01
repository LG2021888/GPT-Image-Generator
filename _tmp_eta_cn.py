from pathlib import Path
p=Path('app/gpt_image_generator.py')
text=p.read_text(encoding='utf-8')
text=text.replace('成功:0 失败:0 进行中:0 成功率:0% 平均:0.0s 最快:-- 最慢:-- ETA:--', '成功:0 失败:0 进行中:0 成功率:0% 平均:0.0s 最快:-- 最慢:-- 预计剩余:--', 1)
text=text.replace('ttk.Label(frame, textvariable=self.stats_var, anchor="e").grid(row=1, column=0, columnspan=4, sticky="ew", pady=(3, 0))', 'ttk.Label(frame, textvariable=self.stats_var, anchor="w").grid(row=1, column=2, columnspan=2, sticky="ew", pady=(3, 0))', 1)
old='''        if self.completed_count and self.running:
            remaining = max(self.total_requests - self.completed_count, 0)
            eta = f"{remaining * avg:.1f}s"
        else:
            eta = "--"
        self.stats_var.set(
            f"成功:{self.success_count} 失败:{self.fail_count} 进行中:{self.in_flight_count} "
            f"成功率:{success_rate:.0f}% 平均:{avg:.1f}s 最快:{fastest} 最慢:{slowest} ETA:{eta}"
        )
'''
new='''        remaining = max(self.total_requests - self.completed_count, 0)
        if remaining == 0 and self.total_requests:
            eta = "0.0s"
        elif self.completed_count and self.running:
            eta = f"{remaining * avg:.1f}s"
        elif self.running:
            eta = "计算中"
        else:
            eta = "--"
        self.stats_var.set(
            f"成功:{self.success_count} 失败:{self.fail_count} 进行中:{self.in_flight_count} "
            f"成功率:{success_rate:.0f}% 平均:{avg:.1f}s 最快:{fastest} 最慢:{slowest} 预计剩余:{eta}"
        )
'''
if old not in text:
    raise SystemExit('update_stats block not found')
text=text.replace(old,new,1)
p.write_text(text,encoding='utf-8')
