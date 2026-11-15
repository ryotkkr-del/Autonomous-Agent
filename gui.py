"""Simple local desktop interface for autonomous-agent-v0.9.

No network service is exposed. Agent commands run in child processes.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import json
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'state.sqlite3'
STOP = ROOT / 'STOP'
MAX_GOAL = 2000


def load_jobs(db_path=DB):
    """Read existing state without constructing/altering DB schema."""
    if not Path(db_path).is_file():
        return []
    db = sqlite3.connect(f'file:{Path(db_path).resolve().as_posix()}?mode=ro', uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in db.execute(
            'SELECT id,goal,status,steps,result,allow_tests,allow_git,workspace_rel,updated '
            'FROM jobs ORDER BY id DESC LIMIT 100')]
    finally:
        db.close()


def job_folder(job, root=ROOT):
    """Only open folders assigned by the agent, never arbitrary stored paths."""
    rel = job.get('workspace_rel') or ''
    if rel and rel != f"jobs/{job['id']}":
        raise ValueError('不正な作業フォルダ情報です')
    folder = Path(root) / 'workspace'
    if rel:
        folder = folder / 'jobs' / str(job['id'])
    base = (Path(root) / 'workspace').resolve()
    if not folder.resolve().is_relative_to(base):
        raise ValueError('作業フォルダ外を参照できません')
    if folder.is_symlink() or (base / 'jobs').is_symlink():
        raise ValueError('シンボリックリンクを開けません')
    return folder


def validate_goal(value):
    value = value.strip()
    if not value:
        raise ValueError('まずAIに達成してほしい目標を入力してください')
    if len(value) > MAX_GOAL:
        raise ValueError(f'目標は{MAX_GOAL}文字以内にしてください')
    return value


def extract_job_id(output):
    match = re.search(r'Created job #\s*(\d+)', output)
    if not match:
        raise ValueError('ジョブ番号を取得できませんでした')
    return int(match.group(1))



STATUS_NAMES = {'paused':'一時停止中', 'running':'実行中', 'done':'完了', 'blocked':'要確認', 'awaiting_approval':'変更の承認待ち'}
REASON_NAMES = {
    'step budget reached':'今回の作業回数が上限に達しました。続けるには「開始 / 再開」を押してください。',
    'STOP file detected':'停止ボタンによって一時停止しました。',
    '4 consecutive errors across runs':'エラーが4回続いたため安全のため停止しました。履歴を確認してください。',
    '4 consecutive errors':'エラーが4回続いたため停止しました。',
    'same action repeated 3 times':'同じ操作が3回続いたため停止しました。',
    'keyboard interruption':'作業が中断されました。',
}
ACTION_NAMES = {
    'list_files':'ファイル一覧を確認', 'read_file':'ファイルを確認',
    'write_file':'ファイルを編集', 'check_python':'Python構文を確認',
    'run_tests':'テストを実行', 'auto_tests':'完了前にテストを実行',
    'read_url':'Webページを確認', 'git_status':'Gitの状態を確認',
    'git_checkpoint':'変更履歴を保存', 'finish':'作業を完了',
    'review_failed':'成果物を再確認', 'codex':'Codexに引き継ぎ',
}

def describe_status(job):
    """Human-friendly status, without inventing progress or completion times."""
    if not job:
        return 'ジョブを選択してください'
    status = job.get('status', '')
    reason = (job.get('result') or '').strip()
    if status == 'done':
        return '完了：' + (reason[:180] or '成果物を確認してください')
    if reason.startswith('ERROR:'):
        return '実行エラー：' + reason[6:180]
    return REASON_NAMES.get(reason, reason[:180] or {
        'paused':'開始・再開で作業を進められます。',
        'running':'AIが作業中です。',
        'blocked':'問題を確認してから再開してください。',
        'awaiting_approval':'AIの変更案を確認して承認・却下してください。',
    }.get(status, '状態を確認してください。'))


def read_job_details(job_id, db_path=DB):
    """Fetch read-only status data; older databases may lack optional tables."""
    result = {'last_action':'', 'task_total':0, 'task_done':0}
    if not Path(db_path).is_file():
        return result
    db = sqlite3.connect(f'file:{Path(db_path).resolve().as_posix()}?mode=ro', uri=True, timeout=3)
    try:
        row = db.execute('SELECT action FROM events WHERE job_id=? ORDER BY id DESC LIMIT 1',(job_id,)).fetchone()
        if row:
            result['last_action'] = ACTION_NAMES.get(row[0], row[0])
        row = db.execute("SELECT count(*), sum(CASE WHEN state='done' THEN 1 ELSE 0 END) FROM plan_tasks WHERE job_id=?",(job_id,)).fetchone()
        if row:
            result['task_total'], result['task_done'] = int(row[0] or 0), int(row[1] or 0)
    except sqlite3.OperationalError:
        # v0.1 databases had no task board.
        pass
    finally:
        db.close()
    return result


def count_outputs(folder, max_items=500):
    """Count ordinary files without following links or scanning untrusted subtrees."""
    if not folder.is_dir() or folder.is_symlink():
        return 0
    count = 0
    try:
        for child in folder.iterdir():
            if child.is_file() and not child.is_symlink() and child.name not in ('.gitignore',):
                count += 1
            elif child.is_dir() and not child.is_symlink() and child.name != '.git':
                for sub in child.iterdir():
                    if sub.is_file() and not sub.is_symlink():
                        count += 1
            if count >= max_items:
                break
    except OSError:
        return count
    return count

class DesktopApp:
    def __init__(self, root):
        self.root = root
        root.title('自律AI - 目標を入力して実行')
        root.geometry('1000x820')
        root.minsize(800, 690)
        self.jobs = {}
        self.selected_id = None
        self.worker = None
        self.proc = None
        self.command_name = ''
        self.last_output = ''
        self.output_file = None
        self.output_pos = 0
        self.goal = tk.StringVar()
        self.selected_label = tk.StringVar(value='ジョブを選択してください')
        self.status_label = tk.StringVar(value='準備中')
        self.steps = tk.IntVar(value=8)
        self.details_label = tk.StringVar(value='ジョブを選ぶと詳細が表示されます')
        self.last_action_label = tk.StringVar(value='')
        self.tests_enabled = tk.BooleanVar(value=False)
        self.git_enabled = tk.BooleanVar(value=False)
        self.search_enabled = tk.BooleanVar(value=False)
        self._build()
        self.refresh()
        root.after(350, self._poll)

    def _build(self):
        self.root.configure(bg='#f6f7f9')
        style = ttk.Style()
        if 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('TFrame', background='#f6f7f9')
        style.configure('TLabel', background='#f6f7f9', font=('Yu Gothic UI', 10))
        style.configure('TButton', font=('Yu Gothic UI', 10), padding=(10, 7))
        style.configure('Treeview', rowheight=30, font=('Yu Gothic UI', 10))
        style.configure('Treeview.Heading', font=('Yu Gothic UI', 10, 'bold'))
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='自律AI', font=('Yu Gothic UI', 21, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='目標を与えて開始。途中で止めても次回続きから再開できます。').pack(anchor='w', pady=(0, 12))
        editor = ttk.Frame(outer); editor.pack(fill='x')
        ttk.Label(editor, text='新しい目標').pack(anchor='w')
        line = ttk.Frame(editor); line.pack(fill='x', pady=(3, 10))
        ttk.Entry(line, textvariable=self.goal, font=('Yu Gothic UI', 11)).pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.create_btn = ttk.Button(line, text='目標を登録', command=self.create_goal)
        self.create_btn.pack(side='right')
        ttk.Label(outer, text='ジョブ一覧', font=('Yu Gothic UI', 11, 'bold')).pack(anchor='w', pady=(7, 3))
        list_frame = ttk.Frame(outer); list_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(list_frame, columns=('id','status','steps','goal'), show='headings', height=6, selectmode='browse')
        for col, label, size in [('id','ID',45),('status','状態',88),('steps','ステップ',75),('goal','目標',500)]:
            self.tree.heading(col,text=label); self.tree.column(col,width=size,stretch=col=='goal',anchor='w')
        yscroll = ttk.Scrollbar(list_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side='left',fill='both',expand=True)
        yscroll.pack(side='right',fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.select_job())
        controls = ttk.Frame(outer); controls.pack(fill='x', pady=(13, 4))
        ttk.Label(controls, textvariable=self.selected_label, font=('Yu Gothic UI', 11, 'bold')).pack(side='left')
        ttk.Label(controls, text='1回の作業数:').pack(side='left', padx=(18, 4))
        ttk.Spinbox(controls, from_=1, to=30, width=4, textvariable=self.steps).pack(side='left')
        summary=ttk.LabelFrame(outer,text='現在の状況',padding=(12,9))
        summary.pack(fill='x',pady=(5,8))
        ttk.Label(summary,textvariable=self.details_label,wraplength=820).pack(anchor='w')
        ttk.Label(summary,textvariable=self.last_action_label,wraplength=820).pack(anchor='w',pady=(5,0))
        actions = ttk.Frame(outer); actions.pack(fill='x', pady=(3, 8))
        self.start_btn=ttk.Button(actions,text='▶ 開始 / 再開',command=self.run_job)
        self.start_btn.pack(side='left',padx=(0,7))
        ttk.Button(actions,text='■ 一時停止',command=self.pause).pack(side='left',padx=(0,7))
        ttk.Button(actions,text='更新',command=self.refresh).pack(side='left',padx=(0,7))
        ttk.Button(actions,text='成果物を開く',command=self.open_folder).pack(side='left',padx=(0,7))
        ttk.Button(actions,text='ChatGPT用レポート',command=self.chat_report).pack(side='left',padx=(0,7))
        ttk.Button(actions,text='計画・履歴',command=self.view_history).pack(side='left')
        more=ttk.Frame(outer);more.pack(fill='x',pady=(0,5))
        ttk.Button(more,text='計画の一覧',command=lambda:self.show_job_info('tasks','計画')).pack(side='left',padx=(0,7))
        ttk.Button(more,text='修正の記録',command=lambda:self.show_job_info('repairs','修正の記録')).pack(side='left',padx=(0,7))
        ttk.Button(more,text='診断の履歴',command=lambda:self.show_job_info('diagnoses','診断の履歴')).pack(side='left',padx=(0,7))
        ttk.Button(more,text='計画を見直す',command=self.replan_job).pack(side='left',padx=(0,7))
        ttk.Button(more,text='停止状態の解除',command=self.unblock_job).pack(side='left')
        checks=ttk.Frame(outer);checks.pack(fill='x',pady=(0,5))
        ttk.Button(checks,text='成功条件を設定',command=self.set_success_criteria).pack(side='left',padx=(0,7))
        ttk.Button(checks,text='成功条件を見る',command=self.view_success_criteria).pack(side='left',padx=(0,7))
        ttk.Button(checks,text='PCへの影響・権限を確認',command=self.view_safety).pack(side='left',padx=(0,7))
        ttk.Button(checks,text='変更案を確認・承認',command=self.review_pending_change).pack(side='left',padx=(0,7))
        ttk.Button(checks,text='変更を元に戻す',command=self.review_rollback).pack(side='left',padx=(0,7))
        ttk.Button(checks,text='旧ジョブの保護を有効化',command=self.protect_legacy_job).pack(side='left')
        opts = ttk.Frame(outer); opts.pack(fill='x', pady=(3, 9))
        self.testbox=ttk.Checkbutton(opts,text='Pythonテスト実行を許可（注意）',variable=self.tests_enabled,command=self.change_tests)
        self.testbox.pack(side='left',padx=(0,18))
        self.gitbox=ttk.Checkbutton(opts,text='ローカルGitを許可',variable=self.git_enabled,command=self.change_git)
        self.gitbox.pack(side='left',padx=(0,18))
        ttk.Button(opts,text='Webページを許可',command=self.approve_web).pack(side='left',padx=(0,12))
        ttk.Checkbutton(opts,text='自動Web検索を許可',variable=self.search_enabled,command=self.change_search).pack(side='left')
        info=ttk.Frame(outer); info.pack(fill='x')
        ttk.Label(info,text='実行ログ',font=('Yu Gothic UI',11,'bold')).pack(side='left')
        ttk.Label(info,textvariable=self.status_label).pack(side='right')
        self.log=tk.Text(outer,height=10,wrap='word',font=('Consolas',10),state='disabled',bg='white')
        self.log.pack(fill='both',expand=True,pady=(4,5))
        helptext='初回は Ollama を起動し、ollama pull gemma3:4b を実行してください。Codex はこの画面から自動起動しません。'
        ttk.Label(outer,text=helptext,wraplength=840).pack(anchor='w')
        bottom=ttk.Frame(outer);bottom.pack(fill='x',pady=(5,0))
        ttk.Button(bottom,text='接続・環境を確認',command=lambda:self.launch(['doctor'],'接続確認')).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='Docker環境を診断',command=self.check_sandbox).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='Pythonイメージを準備',command=self.prepare_sandbox).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='Docker公式サイト',command=lambda:webbrowser.open('https://www.docker.com/products/docker-desktop/')).pack(side='left')

    def _refresh_periodic(self):
        # External scheduled runs can update SQLite independently of this GUI.
        if self.worker is None and self.output_file is None:
            self.refresh()
        self.root.after(2000,self._refresh_periodic)

    def show_job_info(self,command,name):
        job_id=self._current_job()
        if job_id is not None:
            self.launch([command,str(job_id)],f'ジョブ#{job_id} の{name}')

    def unblock_job(self):
        job_id=self._current_job()
        if job_id is None:return
        job=self.jobs[str(job_id)]
        if job['status']!='blocked':
            messagebox.showinfo('解除は不要','このジョブは要確認の状態ではありません。')
            return
        if messagebox.askyesno('停止を解除','問題の原因を確認しましたか？停止状態を解除すると再び操作できます。'):
            self.launch(['unblock',str(job_id)],'停止状態を解除')

    def _append(self, text):
        if not text:return
        self.log.configure(state='normal')
        self.log.insert('end',text)
        self.log.see('end')
        # Avoid unbounded UI memory
        if float(self.log.index('end-1c').split('.')[0]) > 3000:
            self.log.delete('1.0','1000.0')
        self.log.configure(state='disabled')

    def refresh(self, selected=None):
        try: rows=load_jobs()
        except (sqlite3.Error, OSError) as exc:
            self.status_label.set(f'一覧の読み込み失敗: {exc}')
            return
        prev=selected if selected is not None else self.selected_id
        self.jobs={str(r['id']):r for r in rows}
        for item in self.tree.get_children():self.tree.delete(item)
        translations={'paused':'一時停止','running':'実行中','done':'完了','blocked':'要確認','awaiting_approval':'変更の承認待ち'}
        for r in rows:
            self.tree.insert('','end',iid=str(r['id']),values=(r['id'],translations.get(r['status'],r['status']),r['steps'],r['goal'][:140]))
        if prev is not None and str(prev) in self.jobs:
            self.tree.selection_set(str(prev));self.tree.see(str(prev))
        elif rows:
            self.tree.selection_set(str(rows[0]['id']))
        self.select_job()

    def select_job(self):
        chosen=self.tree.selection()
        self.selected_id=int(chosen[0]) if chosen else None
        job=self.jobs.get(str(self.selected_id))
        if not job:
            self.selected_label.set('ジョブを選択してください')
            self.tests_enabled.set(False);self.git_enabled.set(False);self.search_enabled.set(False)
            self.details_label.set('ジョブを選ぶと詳細が表示されます')
            self.last_action_label.set('')
            return
        self.selected_label.set(f"#{job['id']}  {STATUS_NAMES.get(job['status'],job['status'])}  ({job['steps']}ステップ)")
        self.details_label.set(describe_status(job))
        try:
            details=read_job_details(job['id'])
            outputs=count_outputs(job_folder(job))
            progress = (f"計画：{details['task_done']}/{details['task_total']}項目  |  " if details['task_total'] else '計画：未生成  |  ')
            self.last_action_label.set(progress + f"成果物：{outputs}ファイル  |  最後の操作：{details['last_action'] or 'なし'}")
        except (OSError,ValueError,sqlite3.Error) as exc:
            self.last_action_label.set('詳細情報を読み取れません：' + str(exc)[:100])
        self.tests_enabled.set(bool(job['allow_tests']))
        self.git_enabled.set(bool(job['allow_git']))
        try:
            with sqlite3.connect(DB) as db:
                row=db.execute('SELECT allow_search FROM agent_preferences WHERE job_id=?',(job['id'],)).fetchone()
            self.search_enabled.set(bool(row[0]) if row else False)
        except sqlite3.Error:
            self.search_enabled.set(False)

    def _current_job(self):
        if self.selected_id is None:
            messagebox.showinfo('ジョブを選択','先に目標を登録するか、ジョブを選択してください')
            return None
        return self.selected_id

    def launch(self,args,title, on_success=None):
        if self.proc is not None and self.proc.poll() is None:
            messagebox.showinfo('実行中','実行中の処理が終わるまで操作できません')
            return False
        self.command_name=title
        self.status_label.set(f'{title} 実行中')
        self.last_output=''
        self._append('\n── '+title+' ──\n')
        fd,path=tempfile.mkstemp(prefix='agent-ui-',suffix='.log',dir=ROOT)
        os.close(fd)
        self.output_file=Path(path);self.output_pos=0
        def worker():
            try:
                with self.output_file.open('w',encoding='utf-8',errors='replace') as out:
                    # unbuffered to show output promptly
                    self.proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'agent.py'),*args],cwd=ROOT,
                        stdout=out,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
                    self.proc.wait()
            except Exception as exc:
                self.output_file.write_text('起動エラー: '+str(exc),encoding='utf-8')
        self.worker=threading.Thread(target=worker,daemon=True)
        self.worker.start()
        self._on_success=on_success
        return True

    def _poll(self):
        if self.output_file is not None:
            try:
                with self.output_file.open('r',encoding='utf-8',errors='replace') as fp:
                    fp.seek(self.output_pos)
                    chunk=fp.read()
                    self.output_pos=fp.tell()
                if chunk:
                    self.last_output+=chunk
                    self._append(chunk)
            except OSError: pass
            if self.worker is not None and not self.worker.is_alive():
                # Give the final worker write a chance to be seen on the next poll
                if getattr(self,'_finish_pending',False):
                    code=self.proc.returncode if self.proc else -1
                    self.status_label.set('完了' if code==0 else f'エラー (終了コード {code})')
                    on_success=self._on_success if code==0 else None
                    if on_success:
                        try:on_success(self.last_output)
                        except Exception as exc:messagebox.showerror('処理後のエラー',str(exc))
                    self.worker=None;self.proc=None;self._on_success=None
                    self._finish_pending=False
                    try:self.output_file.unlink(missing_ok=True)
                    except OSError:pass
                    self.output_file=None
                    self.refresh()
                else:self._finish_pending=True
            else:self._finish_pending=False
        self.root.after(350,self._poll)
        self.root.after(2000,self._refresh_periodic)

    def create_goal(self):
        try:goal=validate_goal(self.goal.get())
        except ValueError as exc:messagebox.showwarning('目標を確認',str(exc));return
        self.launch(['new',goal],'新しい目標を登録',on_success=self._created)

    def _created(self,output):
        number=extract_job_id(output)
        self.goal.set('')
        self.refresh(selected=number)

    def run_job(self):
        job_id=self._current_job()
        if job_id is None:return
        job=self.jobs[str(job_id)]
        if job['status']=='done':
            messagebox.showinfo('完了','このジョブは完了しています。別の目標を登録してください。');return
        if job['status']=='awaiting_approval':
            messagebox.showinfo('変更の確認が必要','変更案を確認・承認 から内容を確認してください。');return
        if job['status']=='blocked':
            messagebox.showwarning('要確認','このジョブは停止条件に達しています。履歴を確認して解除してください。');return
        try:steps=int(self.steps.get())
        except (ValueError,tk.TclError):steps=8
        if not 1 <= steps <= 30:
            messagebox.showwarning('ステップ数','1〜30を指定してください');return
        if self.proc is not None and self.proc.poll() is None:
            messagebox.showinfo('実行中','先に実行中の処理を終了してください。')
            return
        STOP.unlink(missing_ok=True)
        self.launch(['run',str(job_id),'--steps',str(steps)],f'ジョブ#{job_id} を実行')

    def pause(self):
        # STOP is checked between actions. Does not forcibly terminate an action.
        STOP.touch()
        self.status_label.set('停止を要求しました（現在の操作が終わってから停止）')
        self._append('停止要求を送信しました。\n')

    def open_folder(self):
        job_id=self._current_job()
        if job_id is None:return
        try:
            folder=job_folder(self.jobs[str(job_id)])
            folder.mkdir(parents=True,exist_ok=True)
            if os.name=='nt':os.startfile(str(folder))
            elif sys.platform=='darwin':subprocess.Popen(['open',str(folder)])
            else:subprocess.Popen(['xdg-open',str(folder)])
        except Exception as exc:messagebox.showerror('フォルダを開けません',str(exc))

    def chat_report(self):
        job_id=self._current_job()
        if job_id is None:return
        def callback(_):
            report=ROOT/f'chat-report-{job_id}.md'
            if report.is_file():
                self.root.clipboard_clear();self.root.clipboard_append(report.read_text(encoding='utf-8'))
                messagebox.showinfo('コピー完了','ChatGPTに貼り付けられるレポートをコピーしました。個人情報や秘密が含まれていないか、送信前に確認してください。')
        self.launch(['chat-report',str(job_id)],'ChatGPT用レポートを生成',on_success=callback)

    def view_history(self):
        job_id=self._current_job()
        if job_id is not None:self.launch(['history',str(job_id)],f'ジョブ#{job_id} の実行履歴')

    def replan_job(self):
        job_id=self._current_job()
        if job_id is None:return
        if not messagebox.askyesno('計画の更新','現在の計画を見直します。既存の成果物は保持します。実行しますか？'):return
        self.launch(['replan',str(job_id)],'計画の更新')

    def set_success_criteria(self):
        job_id=self._current_job()
        if job_id is None:return
        name=simpledialog.askstring('成功条件','必須ファイルを1つ指定してください（例: lesson.md）。既存の成功条件は上書きされます。',parent=self.root)
        if name is None:return
        name=name.strip()
        if not name:
            messagebox.showwarning('入力を確認','ファイル名を入力してください');return
        needle=simpledialog.askstring('成功条件','必須文字列（任意）。含まれていることを確認する文字列。空欄なら存在のみ確認。',parent=self.root)
        if needle is None:return
        args=['criteria',str(job_id),'--file',name]
        if needle:args+=['--contains',name+'::'+needle]
        if not messagebox.askyesno('成功条件の保存','ジョブの成功条件をこの設定に置き換えますか？'):return
        self.launch(args,'成功条件を保存')

    def view_success_criteria(self):
        job_id=self._current_job()
        if job_id is not None:self.launch(['criteria-show',str(job_id)],'成功条件を表示')

    def view_safety(self):
        job_id=self._current_job()
        if job_id is None:
            self.launch(['safety'],'アプリの危険性と許可')
        else:
            self.launch(['safety',str(job_id)],'ジョブの権限と危険性')
        messagebox.showwarning('PCの安全性について',
            'このアプリはWindowsのカーネルやドライバーを操作しません。\\n'
            'Pythonテストの実行にはDockerが必須で、'
            'ネットワーク遮断・読み取り専用マウント・権限制限を適用します。\\n'
            '新規ジョブのAI編集は承認が必要です。旧ジョブには保護設定が必要です。'
            'CodexとGitの自動書き込みは保護対象ジョブで無効化します。'
            'コンテナを突破する脆弱性やDocker自体の危険は残ります。'
            '隔離が必要ならWindows Sandboxまたは仮想マシンを利用してください。')

    def check_sandbox(self):
        """Same diagnostic used by CLI; run without blocking the Tk event loop."""
        self.launch(['sandbox-status'],'Docker環境の診断',on_success=self._sandbox_result)

    def _sandbox_result(self, output):
        try:
            result=json.loads(output)
            title='Docker隔離環境の確認'
            text=result.get('message','')+'\\n\\n'+result.get('detail','')+'\\n\\n'+result.get('next_step','')
            if result.get('ready'):
                messagebox.showinfo(title,text)
            else:
                messagebox.showwarning(title,text)
        except (ValueError,TypeError):
            messagebox.showwarning('診断結果','診断ログを確認してください。')

    def prepare_sandbox(self):
        """Only download the image after the user explicitly approves."""
        if not messagebox.askyesno('Pythonイメージの準備',
             'Docker Desktopがすでに起動している場合、公式Pythonイメージ python:3.11-slim をDocker Hubからダウンロードします。\\n'
             'ネットワーク通信とディスク容量を使用します。続けますか？'):
            return
        self.launch(['sandbox-prepare','--confirm'],'Dockerイメージの準備',
                    on_success=lambda _: self.check_sandbox())

    def protect_legacy_job(self):
        job_id=self._current_job()
        if job_id is None:return
        if not messagebox.askyesno('変更の承認を必須にする',
            'ジョブ #'+str(job_id)+' について、今後のAIによるファイル編集をレビュー待ちにします。'
            '以前の作業結果は変更しません。続けますか？'):
            return
        self.launch(['protect-job',str(job_id)],'変更承認の保護を設定')

    def review_pending_change(self):
        job_id=self._current_job()
        if job_id is None:return
        self.launch(['pending',str(job_id)],'未承認の変更を確認',
                    on_success=lambda output:self._choose_pending(job_id,output))

    def _choose_pending(self,job_id,output):
        try:
            items=json.loads(output)
            if not items:
                messagebox.showinfo('変更の承認','保留中の変更はありません。');return
            change_id=items[0]['id']
            ids=[int(item['id']) for item in items]
        except (ValueError,KeyError,IndexError,TypeError):
            messagebox.showerror('読み取りエラー','変更一覧を読み取れませんでした。');return
        # Delay command until after the current worker is fully released.
        if len(ids)>1:
            self.root.after(100,lambda:self.launch(
                ['batch-preview',str(job_id),*[str(i) for i in ids]],
                '一括変更の差分を確認',
                on_success=lambda o:self._show_batch(job_id,ids,o)))
        else:
            self.root.after(100,lambda:self.launch(
                ['change-preview',str(job_id),str(change_id)],
                '変更内容を表示',on_success=lambda o:self._show_change(job_id,change_id,o)))

    def _show_batch(self,job_id,ids,output):
        try:
            result=json.loads(output)
            changes=result['changes']
            if result['truncated'] or len(changes)!=len(ids):
                messagebox.showwarning('一括承認できません','差分が省略されたか一覧が一致しません。CLIで確認してください。')
                return
            display='\\n'.join('=== '+change['path']+' ===\\n'+change['diff'] for change in changes)
        except (ValueError,KeyError,TypeError):
            messagebox.showerror('差分エラー','一括差分を確認できませんでした。');return
        window=tk.Toplevel(self.root)
        window.title('一括承認 — '+str(len(ids))+'ファイル')
        window.geometry('900x640')
        ttk.Label(window,text=str(len(ids))+'ファイルの変更内容を全件確認してください。').pack(padx=12,pady=10)
        view=tk.Text(window,wrap='none',font=('Consolas',10))
        view.insert('1.0',display)
        view.configure(state='disabled')
        view.pack(fill='both',expand=True,padx=12)
        bar=ttk.Frame(window);bar.pack(pady=12)
        def approve():
            if not messagebox.askyesno('一括反映しますか？',
                str(len(ids))+'ファイルを反映します。途中の通常エラーでは復旧を試みますが、停電などでは完全な原子性を保証できません。'):
                return
            window.destroy()
            self.root.after(100,lambda:self.launch(
                ['approve-batch',str(job_id),*[str(i) for i in ids]],'一括変更の承認'))
        ttk.Button(bar,text='すべて承認して反映',command=approve).pack(side='left',padx=10)
        ttk.Button(bar,text='閉じる（変更しない）',command=window.destroy).pack(side='left',padx=10)

    def review_rollback(self):
        job_id=self._current_job()
        if job_id is None:return
        self.launch(['snapshots',str(job_id)],'変更前の履歴を取得',
                    on_success=lambda output:self._choose_rollback(job_id,output))

    def _choose_rollback(self,job_id,output):
        try:
            snapshots=[s for s in json.loads(output) if s['state']=='applied']
            if not snapshots:
                messagebox.showinfo('ロールバック','元に戻せる変更がありません。');return
            choices='\\n'.join(str(s['id'])+' : '+s['path'] for s in snapshots[:15])
        except (ValueError,TypeError,KeyError):
            messagebox.showerror('エラー','履歴を読み取れません。');return
        number=simpledialog.askinteger('変更を元に戻す',
            '戻すスナップショットIDを入力してください。\\n'+choices,parent=self.root)
        if number is None:return
        if not any(x['id']==number for x in snapshots):
            messagebox.showwarning('IDを確認','一覧にない番号は選べません。');return
        if not messagebox.askyesno('復元の最終確認',
            'この変更の直前のファイル内容を復元します。現在の内容が承認後から変わっていた場合は拒否します。'):
            return
        self.root.after(100,lambda:self.launch(
            ['rollback',str(job_id),str(number)],'ファイル変更を復元'))

    def _show_change(self,job_id,change_id,output):
        try:
            change=json.loads(output)
            diff=change['diff']
        except (ValueError,KeyError,TypeError):
            messagebox.showerror('確認できません','変更差分を表示できません。');return
        window=tk.Toplevel(self.root)
        window.title('変更の確認 — '+change['path'])
        window.geometry('820x600')
        ttk.Label(window,text='対象: '+change['path']+'  /  '+change.get('reason',''),
                  wraplength=780).pack(fill='x',padx=12,pady=12)
        view=tk.Text(window,wrap='none',font=('Consolas',10))
        view.insert('1.0',diff or '差分はありません。')
        view.configure(state='disabled')
        view.pack(fill='both',expand=True,padx=12)
        if change.get('truncated'):
            ttk.Label(window,text='差分が長いため省略されています。CLIで完全に確認してから承認してください。').pack()
        bar=ttk.Frame(window);bar.pack(pady=12)
        def finish(approve):
            if approve and change.get('truncated'):
                messagebox.showwarning('差分の省略','この画面では全体を確認できないため、GUIからは承認しません。');return
            if approve and not messagebox.askyesno('変更を反映しますか？',
                    '表示された変更をジョブの作業フォルダへ保存します。ファイルが変わっていた場合は拒否します。'):
                return
            window.destroy()
            command='approve-change' if approve else 'reject-change'
            self.root.after(100,lambda:self.launch(
                [command,str(job_id),str(change_id)],
                '変更を承認' if approve else '変更を却下'))
        ttk.Button(bar,text='承認して反映',command=lambda:finish(True)).pack(side='left',padx=12)
        ttk.Button(bar,text='却下する',command=lambda:finish(False)).pack(side='left',padx=12)
        ttk.Button(bar,text='閉じる',command=window.destroy).pack(side='left',padx=12)

    def change_search(self):
        job_id=self._current_job()
        if job_id is None:return
        enabled=self.search_enabled.get()
        if enabled and not messagebox.askyesno('Web検索の許可','このジョブに限りBingへの検索クエリ送信を許可します。検索結果は未検証の外部データです。許可しますか？'):
            self.search_enabled.set(False);return
        self.launch(['allow-search' if enabled else 'deny-search',str(job_id)],'Web検索権限を変更')

    def approve_web(self):
        job_id=self._current_job()
        if job_id is None:return
        url=simpledialog.askstring('Web参照の許可','AIが参照してよいHTTPSページのURLを入力してください（完全一致）',parent=self.root)
        if url is None:return
        url=url.strip()
        if not url.startswith('https://'):
            messagebox.showwarning('URLを確認','https:// から始まるURLだけ許可できます');return
        if not messagebox.askyesno('参照の許可',f'ジョブ#{job_id} に次のページの読み取りを許可しますか？\n{url}'):
            return
        self.launch(['approve-url',str(job_id),url],'Webページの参照許可')

    def change_tests(self):
        job_id=self._current_job()
        if job_id is None:return
        enabled=self.tests_enabled.get()
        if enabled and not messagebox.askyesno('危険性の確認','PythonテストはDockerの隔離コンテナ内のみで実行します。Docker未準備なら実行を拒否します。完全な安全保証ではありません。許可しますか？'):
            self.tests_enabled.set(False);return
        self.launch(['allow-tests' if enabled else 'deny-tests',str(job_id)],'テスト権限を変更')

    def change_git(self):
        job_id=self._current_job()
        if job_id is None:return
        enabled=self.git_enabled.get()
        if enabled and not messagebox.askyesno('Git操作','作業領域の変更内容がローカルGit履歴に残ります。秘密情報を含まないことを確認してください。許可しますか？'):
            self.git_enabled.set(False);return
        self.launch(['allow-git' if enabled else 'deny-git',str(job_id)],'Git権限を変更')


def main():
    root=tk.Tk()
    DesktopApp(root)
    root.mainloop()

if __name__=='__main__':main()
