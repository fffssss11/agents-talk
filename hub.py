#!/usr/bin/env python3
"""Agents Talk: local collaboration board, CLI and dashboard. Standard library only."""
from __future__ import annotations
import argparse
import contextlib
import html
import hashlib
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('AGENTS_TALK_DATA', str(ROOT))).resolve()
BOARD = DATA / 'board.jsonl'
CONFIG = Path(os.environ.get('AGENTS_TALK_CONFIG', str(ROOT / 'config.json'))).resolve()
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MEDIA = ('image_generate', 'image_edit', 'video_generate')
TYPES = ('join', 'say', 'plan', 'task', 'workflow', 'claim', 'progress', 'done', 'review',
         'question', 'answer', 'decision', 'lock', 'unlock', 'idle', 'leave', 'ack', 'capability', 'blocked', 'intervention', 'usage')
THREAD_LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(32)
MAX_UPLOAD = 32 * 1024 * 1024
RETIRED = {'pi': {'name': 'Pi（历史成员）'}}

def media_intent(text):
    """Conservative lexical backstop for clearly phrased production tasks, not a semantic classifier."""
    text = text.lower()
    if re.search(r'(生成|制作|做|剪辑|编辑|创作|渲染|合成).{0,24}(视频|短片|动画)|(视频|短片|动画)(?:内容|素材|的)?(生成|制作|剪辑|编辑)|\b(generate|create|produce|edit|render)\b.{0,24}\b(video|animation|film)\b', text):
        return 'video_generate'
    if re.search(r'(编辑|修改|处理|修复|裁剪|抠|重绘).{0,18}(图片|图像|照片)|(图片|图像|照片)(编辑|处理|修复)|\b(edit|retouch|crop)\b.{0,18}\b(image|photo|picture)\b', text):
        return 'image_edit'
    if re.search(r'(生成|制作|绘制|画|设计|创作).{0,24}(图片|图像|插图|海报|封面|配图|照片|流程图)|(图片|图像)(?:内容|素材|的)?(生成|制作)|\b(generate|create|draw|design)\b.{0,24}\b(image|illustration|poster|picture)\b', text):
        return 'image_generate'
    return None


def board_text_estimate(text):
    # Rough visible-text budget only; no tokenizer, hidden prompts, tools or media accounting.
    non_ascii = sum(ord(c) > 127 for c in text)
    return non_ascii + (len(text) - non_ascii + 3) // 4


def token_usage(msgs, cfg):
    result = {aid: {'input': None, 'output': None, 'total': None, 'cached_input': None,
                    'reasoning_output': None, 'reports': 0, 'last_report': None,
                    'board_output_estimate': 0, 'sources': []} for aid in cfg['agents']}
    seen = set()
    for m in msgs:
        if m.get('from') not in result: continue
        row = result[m['from']]
        if m['type'] != 'usage':
            row['board_output_estimate'] += board_text_estimate(m.get('body', ''))
            continue
        u = m.get('usage')
        if not u: continue
        key = (m['session'], m['from'], u['id'])
        if key in seen: continue
        seen.add(key)
        for field in ('input', 'output', 'cached_input', 'reasoning_output'):
            if u.get(field) is not None: row[field] = (row[field] or 0) + u[field]
        row['total'] = row['input'] + row['output']
        row['reports'] += 1; row['last_report'] = m['ts']
        source = {'provider': u['provider'], 'model': u['model'], 'source': u['source']}
        if source not in row['sources']: row['sources'].append(source)
    return result

class Reject(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def config():
    path = CONFIG
    if not path.exists() and path == ROOT / 'config.json' and not os.environ.get('AGENTS_TALK_CONFIG'):
        path = ROOT / 'config.example.json'
    try:
        cfg = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(cfg, dict): raise ValueError('配置必须是 JSON 对象')
        agents = cfg.get('agents')
        if not isinstance(agents, dict) or set(agents) != {'claude', 'codex', 'reasonix', 'zcode'}:
            raise ValueError('agents 必须保留四个客户端 ID；额外窗口请在面板登记')
        for aid, actor in agents.items():
            if not isinstance(actor, dict): raise ValueError(f'{aid} 配置无效')
            for field in ('name', 'role', 'color', 'desc'):
                if not isinstance(actor.get(field), str) or not actor[field].strip():
                    raise ValueError(f'{aid}.{field} 必须是非空文本')
            if actor['role'] not in ('lead', 'worker', 'reviewer'): raise ValueError(f'{aid}.role 无效')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', actor['color']): raise ValueError(f'{aid}.color 必须是六位十六进制颜色')
        if cfg.get('lead') not in agents: raise ValueError('默认主管无效')
        if cfg.get('mode', 'leader') not in ('leader', 'roundtable'): raise ValueError('mode 无效')
        if type(cfg.get('shared_context', False)) is not bool: raise ValueError('shared_context 必须是布尔值')
        participants(cfg.get('participants'), cfg, cfg['lead'])
        return cfg
    except (OSError, ValueError, TypeError) as e:
        raise Reject(f'配置读取失败 {path}: {e}') from e

@contextlib.contextmanager
def transaction():
    """Serialize validation AND append across CLI processes and HTTP threads."""
    DATA.mkdir(parents=True, exist_ok=True)
    with THREAD_LOCK:
        with (DATA / '.hub.lock').open('a+b') as f:
            f.seek(0, 2)
            if f.tell() == 0:
                f.write(b'0'); f.flush()
            deadline = time.monotonic() + 15
            while True:
                try:
                    f.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise Reject('黑板正忙，请稍后重试')
                    time.sleep(.05)
            try:
                yield
            finally:
                f.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f, fcntl.LOCK_UN)

def load():
    if not BOARD.exists():
        return []
    out = []
    for i, line in enumerate(BOARD.read_text(encoding='utf-8').splitlines()):
        if not line.strip():
            continue
        try:
            m = json.loads(line)
            if not isinstance(m, dict):
                raise ValueError('message must be an object')
        except (ValueError, TypeError) as e:
            raise Reject(f'黑板第 {i+1} 行损坏，已停止读写以保留现场：{e}')
        m.setdefault('id', f'legacy-{i}')
        m.setdefault('session', 'main')
        m['_i'] = len(out)
        out.append(m)
    return out

def append(m):
    m = {'id': uuid.uuid4().hex, 'ts': now(), **m}
    with BOARD.open('ab') as f:
        f.write((json.dumps(m, ensure_ascii=False) + '\n').encode('utf-8'))
        f.flush(); os.fsync(f.fileno())
    return m

def participants(value, cfg, lead):
    if not isinstance(value, list) or not value or any(not isinstance(a, str) or a not in cfg['agents'] for a in value):
        raise Reject('参与成员必须是非空的有效成员列表')
    if lead not in value: raise Reject('主导成员必须参与会话，请先更换主导成员')
    return list(dict.fromkeys(value))


def session_agents(cfg, session):
    """Legacy IDs remain default instances; additional IDs belong to one board session."""
    agents = {aid: {**a, 'client': aid, 'model': ''} for aid, a in cfg['agents'].items()}
    for aid, instance in session.get('instances', {}).items():
        client = instance['client']
        if client not in cfg['agents']: continue
        agents[aid] = {**cfg['agents'][client], **instance, 'client': client}
    return agents


def client_of(agents, aid):
    return agents.get(aid, {}).get('client', '')


def usage_by_client(msgs, agents, cfg):
    # Keep per-instance dedup IDs distinct when aggregating one client family.
    mapped = []
    for m in msgs:
        client = client_of(agents, m.get('from'))
        if not client: continue
        item = {**m, 'from': client}
        if m.get('usage'): item['usage'] = {**m['usage'], 'id': m['from'] + ':' + m['usage']['id']}
        mapped.append(item)
    return token_usage(mapped, cfg)


def sessions(msgs, cfg):
    result = {'main': {'id': 'main', 'title': '协作工作室', 'status': 'active',
                       'mode': cfg.get('mode', 'leader'), 'lead': cfg['lead'],
                       'shared_context': cfg.get('shared_context', False)}}
    for m in msgs:
        sid = m['session']
        if m['type'] == 'session':
            result[sid] = {'id': sid, 'title': m['body'], 'status': 'active',
                           'mode': m['mode'], 'lead': m['lead'],
                           'shared_context': m.get('shared_context', False)}
        elif sid in result and m['type'] == 'control':
            result[sid]['status'] = m['action']
        elif sid in result and m['type'] == 'settings':
            result[sid].update({k: m[k] for k in ('mode', 'lead', 'shared_context', 'participants') if k in m})
        if sid in result and m['type'] == 'instance':
            instance = m['instance']
            result[sid].setdefault('instances', {})[instance['id']] = instance
            result[sid].update({k: m[k] for k in ('lead', 'participants') if k in m})
        if sid in result and m['type'] in ('settings', 'instance'):
            result[sid]['instance_revision'] = m.get('_i', -1)
        if m['type'] == 'session' and 'participants' in m:
            result[sid]['participants'] = m['participants']
    for s in result.values():
        s.setdefault('instances', {})
        s.setdefault('instance_revision', -1)
        known = session_agents(cfg, s)
        s.setdefault('participants', list(dict.fromkeys([*cfg.get('participants', ['claude', 'codex', 'reasonix']), s['lead']])))
        # Retired identities stay in historical events/ownership, never impersonate ZCode.
        s['retired_participants'] = [a for a in s['participants'] if a not in known]
        s['participants'] = [a for a in s['participants'] if a in known]
        s['migration_required'] = s['lead'] not in known
        if not s['participants']: s['participants'] = list(cfg['participants'])
    return result


def owns(owner, aid, sid):
    return owner.get('agent') == aid and owner.get('session') == sid


def overlaps(a, b):
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


@contextlib.contextmanager
def listener_slot(sid, aid):
    """OS-held slot: one waiter per identity/session, released even after process death."""
    directory = DATA / '.listeners'; directory.mkdir(exist_ok=True)
    with (directory / f'{sid}.{aid}.lock').open('a+b') as f:
        f.seek(0, 2)
        if not f.tell(): f.write(b'0'); f.flush()
        f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: raise Reject('此成员在该会话已有监听调用，请等待原调用返回，不要重复监听')
        try: yield
        finally:
            f.seek(0)
            if os.name == 'nt': msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(f, fcntl.LOCK_UN)

def canonical_file(value):
    if not isinstance(value, str) or not value.strip():
        raise Reject('文件路径不能为空')
    p = (ROOT / value.replace('\\', '/')).resolve()
    allowed = (ROOT / 'workspace').resolve()
    if not p.is_relative_to(allowed) or p == allowed:
        raise Reject('协作写入仅允许 workspace/ 内的具体文件')
    return os.path.normcase(str(p)).replace('\\', '/')

def derive(msgs, cfg, sid):
    ss = sessions(msgs, cfg)
    if sid not in ss:
        raise Reject('会话不存在')
    current = ss[sid]
    definitions = session_agents(cfg, current)
    agents = {aid: {**a, 'id': aid, 'status': '未接入', 'last': None,
                    'msgs': 0, 'holding': [], 'capabilities': {}} for aid, a in definitions.items()}
    tasks, locks = {}, {}
    feed = [m for m in msgs if m['session'] == sid]
    for m in msgs:
        who, typ = m.get('from'), m['type']
        if typ == 'lock':
            for path in m.get('files', []):
                locks[path] = {'agent': who, 'session': m['session']}
                if m.get('task'): locks[path]['task'] = m['task']
        elif typ == 'unlock':
            for path in m.get('files') or list(locks):
                if owns(locks.get(path, {}), who, m['session']) and (not m.get('task') or locks[path].get('task') == m['task']):
                    del locks[path]
    for m in feed:
        who, typ, tid = m.get('from'), m['type'], m.get('task')
        if who in agents:
            a = agents[who]; a['last'] = m['ts']; a['msgs'] += 1
            a['status'] = {'idle': '等待中', 'claim': '工作中', 'progress': '工作中',
                           'done': '待审查', 'blocked': '受阻'}.get(typ, '已发言')
            if typ == 'capability':
                a['capabilities'][m['kind']] = {'status': m['availability'], 'detail': m['body']}
        if typ == 'task':
            tasks[tid] = {**m, 'id': tid, 'title': m['body'].splitlines()[0][:100],
                          'source_id': m['id'], 'owner': m['to'][0], 'state': '待办', 'log': [],
                          'initial_workflow': {k: m[k] for k in ('reviewer', 'stage', 'integration_plan') if k in m}}
        elif tid in tasks:
            task = tasks[tid]
            if typ == 'workflow':
                for field in ('reviewer', 'stage', 'integration_plan'):
                    if field in m: task[field] = m[field]
            if typ == 'reassign':
                task['owner'] = m['to'][0]; task['state'] = '待办'
            states = {'claim': '进行中', 'progress': '进行中', 'done': '待审查', 'blocked': '受阻'}
            if typ in states: task['state'] = states[typ]
            if typ == 'review': task['state'] = '已完成' if m['verdict'] == 'pass' else '被打回'
            task['log'].append(m)
    for task in tasks.values():
        task['depends_on'] = task.get('depends_on', [])
        task['waiting_for'] = [tid for tid in task['depends_on'] if tasks.get(tid, {}).get('state') != '已完成']
        task['ready'] = not task['waiting_for']
        task['dependency_revision'] = max((m['_i'] for tid in task['depends_on'] if tid in tasks
                                           for m in [tasks[tid], *tasks[tid]['log']]), default=-1)
    for aid, a in agents.items():
        p = DATA / '.presence' / f'{sid}.{aid}.json'
        if p.exists():
            presence = json.loads(p.read_text(encoding='utf-8'))
            age = time.time() - presence['time']
            a['last_seen'] = presence['ts']
            a['online'] = age < 120
            a['last_read'] = presence.get('read_ts')
            a['read_age_seconds'] = max(0, int(time.time() - presence['read_time'])) if 'read_time' in presence else None
        else:
            a['online'] = False
        if not a['online'] and a['last']: a['status'] = '心跳过期'
        if a['online'] and a['status'] == '未接入': a['status'] = '已连接'
        a['holding'] = [p for p, owner in locks.items() if owns(owner, aid, sid)]
        a['enabled'] = aid in current['participants']
        lifecycle = next((m['type'] for m in reversed(feed) if m.get('from') == aid and m['type'] in ('join', 'leave')), None)
        a['detached'] = lifecycle == 'leave'
        a['needs_attention'] = (a['enabled'] and current['status'] != 'ended' and
                                (a['detached'] or a.get('read_age_seconds') is None or a['read_age_seconds'] >= 120))
        if a['detached']: a['status'] = '已退出读取'; a['online'] = False
        if not a['enabled']: a['online'] = False; a['status'] = '未参与'
    return {'session': current, 'sessions': list(ss.values()), 'agents': agents,
            'tasks': list(tasks.values()), 'locks': locks, 'messages': feed, 'total': len(feed),
            'mode': current['mode'], 'lead': current['lead'],
            'token_usage': token_usage(feed, {'agents': definitions}),
            'token_usage_clients': usage_by_client(feed, definitions, cfg),
            'retired_token_usage': token_usage(feed, {'agents': RETIRED})}

def touch(sid, aid, reading=False):
    directory = DATA / '.presence'; directory.mkdir(exist_ok=True)
    path = directory / f'{sid}.{aid}.json'
    presence = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    presence.update(time=time.time(), ts=now())
    if reading: presence.update(read_time=time.time(), read_ts=now())
    path.write_text(json.dumps(presence), encoding='utf-8')


def continuation(st, aid):
    """Small, deterministic next step, independent of message cursor and task pagination."""
    sid = st['session']['id']
    action = 'listen'
    instruction = '继续调用 listen；正常等待超时无需重复读协议或发送 idle，不因单次超时结束回合。'
    own = [t['id'] for t in st['tasks'] if t['owner'] == aid and t['ready'] and t['state'] in ('待办', '进行中', '被打回')]
    if st['session']['status'] == 'ended' or aid not in st['session']['participants'] or st['agents'][aid]['detached']:
        action, instruction = 'exit', '停止新工作，确认待处理控制并释放自己的占用后退出；用户要求退出时优先遵从。'
    elif pending(st['messages'], sid, aid):
        action, instruction = 'ack', '先读取并逐条确认 pending_interventions，再核对最新状态。'
    elif st['session']['migration_required']:
        action, instruction = 'paused_wait', '旧主导成员已停用，请人类选择新的主导成员，确认前不开展新工作。'
    elif st['session']['status'] == 'paused':
        action, instruction = 'paused_wait', '暂停新工作，在安全步骤释放占用并继续 listen 等待恢复。'
    elif own:
        action, instruction = 'execute', '按 task_ids 读取自己的任务摘要并执行或报告受阻；已读消息不代表任务已完成。'
    return {'action': action, 'instruction': instruction, 'task_ids': own[:30] if action == 'execute' else [],
            'listen_argv': [sys.executable, str(ROOT / 'hub.py'), 'listen', '--agent', aid, '--session', sid, '--timeout', '50']}


def binding_path(client_session):
    if not isinstance(client_session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', client_session):
        raise Reject('客户端会话编号无效，请使用实际 session ID')
    return DATA / '.bindings' / (hashlib.sha256(client_session.encode()).hexdigest() + '.json')


def bind_client(sid, aid, client_session, detach=False):
    with transaction():
        st = derive(load(), config(), sid)
        if client_of(st['agents'], aid) != 'claude': raise Reject('当前原生 Stop hook 仅支持 Claude 实例')
        path = binding_path(client_session)
        if detach:
            if path.exists():
                old = json.loads(path.read_text(encoding='utf-8'))
                if old['session'] != sid or old['agent'] != aid: raise Reject('绑定不属于此协作会话')
                path.unlink()
            return {'detached': True}
        if aid not in st['session']['participants'] or st['session']['status'] == 'ended': raise Reject('当前成员或会话不可接入')
        last_join = next((m['type'] for m in reversed(st['messages']) if m.get('from') == aid and m['type'] in ('join', 'leave')), None)
        if last_join != 'join': raise Reject('请先以当前成员身份 join 报到，再绑定原生窗口')
        if path.exists():
            old = json.loads(path.read_text(encoding='utf-8'))
            if old['session'] != sid or old['agent'] != aid: raise Reject('客户端已绑定其他会话或实例，请先 detach')
        path.parent.mkdir(exist_ok=True)
        for existing in path.parent.glob('*.json'):
            if existing == path: continue
            bound = json.loads(existing.read_text(encoding='utf-8'))
            if bound.get('session') == sid and bound.get('agent') == aid:
                raise Reject('此实例已绑定另一原生窗口；并发窗口请创建独立实例')
        path.write_text(json.dumps({'session': sid, 'agent': aid}), encoding='utf-8')
        return {'bound': True, 'session': sid, 'agent': aid}


def stop_guard(event):
    """Read-only guard; never reads transcripts, advances unread cursors or fakes presence."""
    if event.get('hook_event_name') != 'Stop' or event.get('stop_hook_active'): return {}
    path = binding_path(event.get('session_id'))
    with transaction():
        if not path.exists(): return {}
        bound = json.loads(path.read_text(encoding='utf-8'))
        st = derive(load(), config(), bound['session'])
        step = continuation(st, bound['agent'])
        if step['action'] == 'exit': return {}
        return {'decision': 'block', 'reason': 'Agents Talk 协作仍在接入状态。' + step['instruction'] +
                ' 下一次读取参数：' + json.dumps(step['listen_argv'], ensure_ascii=False) +
                ' 若用户已要求停止或客户端无法继续，先发布 leave 说明原因并释放占用，再退出。此提醒仅拦截一次连续结束尝试。'}

def pending(msgs, sid, aid):
    acked = {m.get('reply_to') for m in msgs if m['session'] == sid and m.get('from') == aid and m['type'] == 'ack'}
    return [m for m in msgs if m['session'] == sid and m['type'] in ('intervention', 'control')
            and ('all' in m.get('to', []) or aid in m.get('to', [])) and m['id'] not in acked]


def task_digest(task):
    """Extract source-backed facts; no generated inference or historical log in context."""
    events = [{**task, 'id': task['source_id']}, *task['log']]
    latest = events[-1]
    result = {k: task[k] for k in ('id', 'title', 'owner', 'state', 'depends_on', 'waiting_for', 'ready')}
    result.update(revision=max(task['dependency_revision'], max(m['_i'] for m in events)), source_id=latest['id'],
                  kind=task.get('kind'), summary='', result='', verification='', blockers='')
    for field in ('reviewer', 'stage', 'integration_plan'):
        if field in task: result[field] = task[field]
    sources = {}
    for field in ('summary', 'result', 'verification', 'blockers'):
        found = next((m for m in reversed(events) if field in m), None)
        if found:
            result[field] = found[field][:400]
            sources[field] = found['id']
    if not result['summary']:
        result['summary'] = task.get('body', '')[:400]
        sources['summary'] = task['source_id']
    done = next((m for m in reversed(events) if m['type'] == 'done'), None)
    review = next((m for m in reversed(events) if m['type'] == 'review'), None)
    if done and not result['result']:
        result['result'] = done['body'][:400]; sources['result'] = done['id']
    if review:
        result['review'] = {'by': review['from'], 'verdict': review['verdict'], 'body': review['body'][:400], 'source_id': review['id']}
    # Keep provenance explicit: a past report can coexist with a newer blocked/rework state.
    result['sources'] = sources
    all_files = list(dict.fromkeys(f for m in events for f in m.get('files', [])))
    result['files'] = all_files[:12]
    result['truncated'] = any(len(m.get('body', '')) > 400 for m in (task, latest, done, review) if m) or len(all_files) > 12
    if latest['type'] in ('progress', 'blocked', 'claim') and 'summary' not in latest:
        result['latest_update'] = {'body': latest['body'][:400], 'source_id': latest['id']}
    result['attachments'] = [a for m in events for a in m.get('attachments', [])][-8:]
    return result


def agent_scope(st, aid):
    """Apply the same task/message boundary to read, wait, tasks, status and HTTP context."""
    broad = st['session']['shared_context'] or aid == st['lead']
    tasks = [t for t in st['tasks'] if broad or t['owner'] in (aid, st['lead'])]
    task_ids = {t['id'] for t in tasks}
    def visible(m):
        # Filter task-scoped messages before considering their author or broadcast target.
        if m.get('task') and m['task'] not in task_ids: return False
        who = m.get('from')
        to = m.get('to', ['all'])
        if who == 'human': return 'all' in to or aid in to or aid == st['lead']
        if broad: return True
        if who == aid: return True
        if who == st['lead']: return 'all' in to or aid in to or m.get('task') in task_ids
        # Reviews of own work remain visible; unrelated peer broadcasts are excluded.
        return bool(m.get('task') in task_ids)
    return tasks, [m for m in st['messages'] if visible(m)]


def agent_context(st, aid, *, since=-1, task_id=None, offset=0, task_limit=30,
                  message_limit=20, full=False, message_id=None, feed=None):
    if aid not in st['agents']: raise Reject('当前会话不存在此实例身份')
    tasks, visible = agent_scope(st, aid)
    revision = max((m['_i'] for m in st['messages']), default=-1)
    if since > revision: raise Reject('上下文版本超过当前会话，请从完整摘要重新读取')
    refresh = since < 0 or any(m['type'] in ('settings', 'instance') and m['_i'] > since for m in st['messages'])
    if task_id:
        tasks = [t for t in tasks if t['id'] == task_id]
        if not tasks: raise Reject('任务不存在或不在当前上下文范围')
        visible = [m for m in visible if m.get('task') == task_id]
    if message_id:
        visible = [m for m in visible if m['id'] == message_id]
        if not visible: raise Reject('消息不存在或不在当前上下文范围')
    digests = [task_digest(t) for t in tasks]
    if not refresh and not task_id: digests = [t for t in digests if t['revision'] > since]
    # Stable task order keeps offset pagination deterministic for a fixed revision.
    count = len(digests)
    page = digests[offset:offset + task_limit]
    source_feed = visible if feed is None else [m for m in feed if m['id'] in {v['id'] for v in visible}]
    if feed is None and not message_id:
        source_feed = [m for m in source_feed if m['_i'] > since]
        if not full:
            source_feed = [m for m in source_feed if not m.get('task') and m['type'] in
                           ('say', 'plan', 'question', 'answer', 'decision', 'intervention', 'control', 'settings', 'instance')]
    chosen = source_feed[-message_limit:]
    messages = []
    for m in chosen:
        item = {k: v for k, v in m.items() if k not in ('request_id', 'session_request_id', 'request_hash', 'session')}
        if not full and len(item.get('body', '')) > 800:
            item['body'] = item['body'][:800]; item['truncated'] = True
        messages.append(item)
    session_view = {**st['session']}
    if aid != st['lead'] and not st['session']['shared_context']:
        session_view['instances'] = {key: value for key, value in st['session'].get('instances', {}).items() if key in (aid, st['lead'])}
    result = {'session': session_view, 'agent': aid,
              'identity': {k: st['agents'][aid].get(k) for k in ('id', 'client', 'name', 'model', 'role')},
              'context': {'scope': 'team' if st['session']['shared_context'] else 'focused',
                          'lead_overview': aid == st['lead'], 'revision': revision,
                          'refresh': refresh, 'task_count': count, 'task_offset': offset,
                          'next_task_offset': offset + len(page) if offset + len(page) < count else None,
                          'messages_omitted': max(0, len(source_feed) - len(chosen)),
                          'detail_hint': 'read --agent <我> --session <会话> --task <编号> --full；长消息用 --message <ID> --full'},
              'tasks': page, 'messages': messages,
              'pending_interventions': pending(st['messages'], st['session']['id'], aid),
              'locks': st['locks']}
    result['participation'] = {'enabled': aid in st['session']['participants'],
        'members': st['session']['participants'],
        'instruction': '只给参与成员派工；未参与时释放占用并退出，需人工启用后接入。',
        'tasks_needing_reassignment': [t['id'] for t in tasks if t['owner'] not in st['session']['participants'] and t['state'] != '已完成']}
    result['identity']['role'] = 'lead' if aid == st['lead'] else ('reviewer' if st['agents'][aid]['role'] == 'reviewer' else 'worker')
    result['token_usage'] = st['token_usage'] if aid == st['lead'] or st['session']['shared_context'] else {aid: st['token_usage'][aid]}
    result['continuation'] = continuation(st, aid)
    if aid == st['lead']:
        result['team_health'] = {key: {k: a.get(k) for k in ('last_read', 'needs_attention', 'detached')}
                                 for key, a in st['agents'].items() if a['enabled']}
    if full and task_id:
        result['task_brief'] = {k: v for k, v in tasks[0].items() if k != 'log'}
    return result

def attachment(aid):
    if not re.fullmatch('[a-f0-9]{32}', str(aid)):
        raise Reject('无效附件编号')
    p = DATA / 'uploads' / (aid + '.json')
    if not p.exists(): raise Reject('附件不存在')
    return json.loads(p.read_text(encoding='utf-8'))

def save_attachment(name, content):
    if not content or len(content) > MAX_UPLOAD: raise Reject('附件大小需介于 1 字节和 32 MB')
    name = re.split(r'[/\\]', name)[-1][:160] or 'attachment'
    ext = Path(name).suffix.lower()
    # Only passive, recognized media receive inline MIME types.
    mime = 'application/octet-stream'
    if ext == '.png' and content.startswith(b'\x89PNG\r\n\x1a\n'): mime = 'image/png'
    elif ext in ('.jpg', '.jpeg') and content.startswith(b'\xff\xd8\xff'): mime = 'image/jpeg'
    elif ext == '.gif' and content[:6] in (b'GIF87a', b'GIF89a'): mime = 'image/gif'
    elif ext == '.webp' and content[:4] == b'RIFF' and content[8:12] == b'WEBP': mime = 'image/webp'
    elif ext == '.mp4' and content[4:8] == b'ftyp': mime = 'video/mp4'
    elif ext == '.webm' and content.startswith(b'\x1aE\xdf\xa3'): mime = 'video/webm'
    aid = uuid.uuid4().hex
    folder = DATA / 'uploads'; folder.mkdir(parents=True, exist_ok=True)
    (folder / (aid + '.bin')).write_bytes(content)
    result = {'id': aid, 'name': name, 'size': len(content), 'mime': mime,
              'url': '/media/' + aid, 'path': str(folder / (aid + '.bin'))}
    (folder / (aid + '.json')).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result

def post(payload, human=False):
    with transaction():
        cfg, msgs = config(), load()
        sid = payload.get('session')
        if not sid: raise Reject('必须指定 --session，先用 sessions 查询会话编号')
        st = derive(msgs, cfg, sid)
        cfg = {**cfg, 'agents': st['agents']}
        who = 'human' if human else payload.get('from')
        typ = payload.get('type', 'say')
        retired_cleanup = who in RETIRED and typ in ('unlock', 'leave', 'ack', 'usage')
        if not human and who not in cfg['agents'] and not retired_cleanup: raise Reject('未知或已停用 agent')
        if typ not in TYPES: raise Reject('未知消息类型')
        if human and typ not in ('say', 'intervention', 'task'): raise Reject('网页仅允许发送需求、干预或媒体任务')
        if not human and typ == 'intervention': raise Reject('intervention 仅供人工干预')
        to = payload.get('to') or ['all']
        if isinstance(to, str): to = to.split(',')
        if not isinstance(to, list) or not all(isinstance(x, str) and x in (*cfg['agents'], 'all', 'human') for x in to):
            raise Reject('接收对象无效')
        body = payload.get('body', '')
        if not isinstance(body, str) or len(body) > 100000: raise Reject('正文无效或超过 100000 字符')
        body = body.strip()
        if not body and typ not in ('idle', 'unlock', 'usage'): raise Reject('请输入消息内容')
        request_id = payload.get('request_id')
        if request_id:
            if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', str(request_id)): raise Reject('无效请求编号')
            old = next((m for m in msgs if m.get('request_id') == request_id and m['session'] == sid and m.get('from') == who), None)
            if old: return old
        if not human and who not in st['session']['participants'] and typ not in ('ack', 'unlock', 'idle', 'leave', 'usage'):
            raise Reject('你未参与此会话，请让用户在面板启用后接入；可释放已有占用')
        if typ not in ('ack', 'unlock', 'idle', 'leave'):
            unavailable = [a for a in to if a in cfg['agents'] and a not in st['session']['participants']]
            if unavailable: raise Reject('成员未参与，不能派工或定向发送：' + ', '.join(unavailable))
        if st['session']['status'] == 'ended' and typ not in ('ack', 'unlock', 'idle', 'leave', 'usage'):
            raise Reject('会话已结束，请创建新会话并重新接入')
        if typ in ('task', 'workflow', 'claim', 'progress', 'done', 'lock', 'decision', 'review'):
            if st['session']['migration_required']: raise Reject('旧主导成员已停用，请人类先选择新的主导成员')
            if st['session']['status'] != 'active': raise Reject('会话暂停中，请等待恢复')
            if not human and pending(msgs, sid, who): raise Reject('请先读取并 ack 人工干预或控制信号')
        tid = payload.get('task')
        kind = payload.get('kind')
        if typ == 'usage' and tid: raise Reject('usage 按成员记录独立调用，请勿附带 --task')
        if typ == 'task':
            detected = media_intent(body + '\n' + str(payload.get('summary', '')))
            kind = kind or detected
            if detected == 'video_generate' and kind != 'video_generate': raise Reject('正文涉及视频制作，请按 video_generate 派发')
        taskmap = {t['id']: t for t in st['tasks']}
        if typ in ('task', 'workflow', 'claim', 'progress', 'done', 'review', 'blocked'):
            if not isinstance(tid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', tid): raise Reject('需要有效 --task 编号')
        if typ == 'task':
            if tid in taskmap: raise Reject('任务编号已存在')
            if len(to) != 1 or to[0] not in cfg['agents']: raise Reject('任务必须指定一名成员')
            if not human and who != st['lead']: raise Reject('仅主导成员或人工可以派发任务')
            if human and kind not in MEDIA: raise Reject('网页任务需指定媒体类型')
            if kind and kind not in MEDIA: raise Reject('未知媒体类型')
            if kind and client_of(cfg['agents'], to[0]) not in ('codex', 'claude'): raise Reject('媒体任务只允许 Codex 或 Claude 实例执行')
            deps = payload.get('depends_on', [])
            if isinstance(deps, str): deps = deps.split(',')
            if not isinstance(deps, list) or len(deps) > 100 or any(not isinstance(d, str) or d == tid or d not in taskmap for d in deps):
                raise Reject('depends_on 必须引用同会话已创建的前置任务，不允许自依赖或未创建编号')
            deps = list(dict.fromkeys(deps))
        elif payload.get('depends_on') is not None: raise Reject('依赖仅在创建任务时指定，按依赖顺序发布任务')
        workflow_fields = ('reviewer', 'stage', 'integration_plan')
        if typ == 'workflow':
            if who != st['lead']: raise Reject('仅主导成员可以更新协作安排')
            if tid not in taskmap: raise Reject('任务不存在')
            if taskmap[tid]['state'] == '已完成': raise Reject('已完成任务保留实际记录，不再修改安排')
            if type(payload.get('task_revision')) is not int or payload['task_revision'] != task_digest(taskmap[tid])['revision']:
                raise Reject('请读取任务并携带最新 --task-revision 更新安排')
            if not any(f in payload for f in workflow_fields): raise Reject('请指定要更新的协作安排')
        if any(f in payload for f in workflow_fields):
            if typ not in ('task', 'workflow'): raise Reject('协作安排仅用于 task / workflow')
            plan = {**(taskmap[tid] if typ == 'workflow' else {}), **{f: payload[f] for f in workflow_fields if f in payload}}
            reviewer = plan.get('reviewer', '')
            owner = taskmap[tid]['owner'] if typ == 'workflow' else to[0]
            if not isinstance(reviewer, str) or (reviewer and (reviewer not in st['session']['participants'] or reviewer == owner)):
                raise Reject('验收人必须是参与中的独立成员；空字符串可清除预定验收人')
            if plan.get('stage', 'execution') not in ('execution', 'integration'): raise Reject('stage 必须为 execution 或 integration')
            if plan.get('stage') == 'integration' and not (taskmap[tid]['depends_on'] if typ == 'workflow' else deps):
                raise Reject('整合任务必须通过 depends_on 指定前置交付')
            if not isinstance(plan.get('integration_plan', ''), str) or len(plan.get('integration_plan', '')) > 400:
                raise Reject('integration_plan 需要不超过 400 字符的整合说明')
        if typ in ('claim', 'progress', 'done', 'review', 'blocked'):
            if tid not in taskmap: raise Reject('任务不存在')
            task = taskmap[tid]
            if typ in ('claim', 'progress', 'done') and not task['ready']:
                raise Reject('前置任务尚未审查通过：' + ', '.join(task['waiting_for']))
            task_kind = task.get('kind') or media_intent(task['body'])
            if typ in ('claim', 'progress', 'done') and task_kind and client_of(cfg['agents'], who) not in ('codex', 'claude'):
                raise Reject('图片或视频制作仅由 Codex / Claude 执行，请让主导转交任务')
            if typ == 'review':
                if who == task['owner']: raise Reject('不能审查自己的任务')
                if task.get('reviewer') and who != task['reviewer']: raise Reject('请由指定验收人审查，或让主导先更新 reviewer')
                active_reviewers = [a for a in st['session']['participants'] if cfg['agents'][a].get('role') == 'reviewer']
                if not task.get('reviewer') and who != st['lead'] and who not in active_reviewers and active_reviewers:
                    raise Reject('由主导成员或本次参与的审查员验收')
                if task['state'] != '待审查': raise Reject('任务尚未提交审查')
                if payload.get('verdict') not in ('pass', 'fail'): raise Reject('审查需 --verdict pass|fail')
                if any(owns(owner, task['owner'], sid) and
                       (owner.get('task') == tid or (not owner.get('task') and (not task.get('files') or any(overlaps(path, f) for f in task['files']))))
                       for path, owner in st['locks'].items()):
                    raise Reject('执行者仍持有本任务文件占用，请先释放，再核对最终内容并审查')
            else:
                if who != task['owner']: raise Reject('只有任务负责人可以更新执行状态')
                allowed = {'claim': ('待办', '被打回', '受阻'), 'progress': ('进行中',),
                           'done': ('进行中',), 'blocked': ('待办', '进行中', '被打回', '受阻')}
                if task['state'] not in allowed[typ]: raise Reject('任务状态不允许此操作')
                if typ == 'claim' and task_kind:
                    cap = st['agents'][who]['capabilities'].get(task_kind, {})
                    if cap.get('status') != 'available': raise Reject('请先验证工具并报告 available 能力；不可用时报告 blocked')
        if typ in ('question', 'answer') and to == ['all']: raise Reject('提问或回答需指定对象')
        if typ == 'decision' and who != st['lead']: raise Reject('仅主导成员可以发布 decision')
        if typ == 'capability':
            if client_of(cfg['agents'], who) not in ('claude', 'codex') or kind not in MEDIA: raise Reject('仅 Codex / Claude 实例可报告媒体能力')
            if payload.get('availability') not in ('available', 'unavailable', 'unverified'): raise Reject('能力状态无效')
        if typ == 'ack':
            if payload.get('reply_to') not in {m['id'] for m in pending(msgs, sid, who)}:
                raise Reject('确认对象无效、未发给自己或已经确认')
        for field in ('summary', 'result', 'verification', 'blockers'):
            if field in payload:
                if typ not in ('task', 'progress', 'done', 'review', 'blocked'):
                    raise Reject('结构化摘要仅用于任务及交付消息')
                if not isinstance(payload[field], str) or len(payload[field]) > 400:
                    raise Reject(f'{field} 需要不超过 400 字符的文本，详细证据放正文')
        files = payload.get('files') or []
        if isinstance(files, str): files = files.split(',')
        if not isinstance(files, list): raise Reject('files 必须是路径列表')
        if typ in ('lock', 'unlock', 'task', 'progress', 'done'): files = list(dict.fromkeys(canonical_file(f) for f in files))
        if typ == 'lock':
            if not files: raise Reject('lock 需要 --files')
            if tid:
                task = taskmap.get(tid)
                if not task or task['owner'] != who or task['state'] != '进行中' or not task['ready']:
                    raise Reject('任务文件占用需要先认领自己的就绪任务')
                if type(payload.get('task_revision')) is not int or payload['task_revision'] != task_digest(task)['revision']:
                    raise Reject('请 read 当前任务并使用最新 --task-revision 申请文件占用，避免修改过期内容')
                if task.get('files') and any(f not in task['files'] for f in files): raise Reject('文件不在本任务声明的写入范围')
            for path in files:
                if not tid and any(any(overlaps(path, f) for f in t.get('files', [])) and t['state'] != '已完成' for t in st['tasks']):
                    raise Reject('此文件属于已声明的任务，请 lock 时指定 --task 并先认领')
                # Parent/child paths conflict as well; Windows aliases normalized above.
                for held, owner in st['locks'].items():
                    same_or_legacy = owner.get('task') == tid or (tid and not owner.get('task'))
                    if overlaps(path, held) and (not owns(owner, who, sid) or not same_or_legacy):
                        raise Reject(f'文件被 {owner["agent"]} 占用（会话 {owner["session"]}）：{held}')
        if typ in ('progress', 'done'):
            for path in files:
                owner = st['locks'].get(path, {})
                legacy_lock = not owner.get('task') and not taskmap[tid].get('files')
                if not owns(owner, who, sid) or (owner.get('task') != tid and not legacy_lock):
                    raise Reject('报告修改文件前需取得本任务的文件占用')
        attachments = payload.get('attachments') or []
        if not isinstance(attachments, list) or len(attachments) > 8: raise Reject('最多 8 个附件')
        attachments = [attachment(a['id'] if isinstance(a, dict) else a) for a in attachments]
        if typ == 'task' and kind == 'image_edit' and not any(a['mime'].startswith('image/') for a in attachments):
            raise Reject('图像编辑任务需要附上参考图片')
        m = {'session': sid, 'from': who, 'to': to, 'type': typ, 'body': body}
        if typ == 'usage':
            usage_id = payload.get('usage_id')
            if not isinstance(usage_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', usage_id): raise Reject('usage 需要唯一调用编号 --usage-id')
            u = {'id': usage_id}
            for key, flag in [('input','input_tokens'), ('output','output_tokens'), ('cached_input','cached_input_tokens'), ('reasoning_output','reasoning_output_tokens')]:
                value = payload.get(flag)
                if value is None and key in ('cached_input', 'reasoning_output'): continue
                if type(value) is not int or not 0 <= value <= 10**12: raise Reject(flag + ' 必须是非负整数')
                u[key] = value
            if u.get('cached_input', 0) > u['input'] or u.get('reasoning_output', 0) > u['output']:
                raise Reject('缓存输入包含在 input 内，推理输出包含在 output 内，不可重复累加')
            for field in ('provider', 'model', 'source'):
                value = payload.get('usage_source' if field == 'source' else field)
                if not isinstance(value, str) or not value.strip() or len(value) > 300: raise Reject('usage 需要 provider、model、usage-source 来源说明')
                u[field] = value.strip()
            old = next((e for e in msgs if e['session'] == sid and e.get('from') == who and e.get('usage', {}).get('id') == usage_id), None)
            if old:
                if old['usage'] != u: raise Reject('相同调用编号已有不同用量，请核对来源，禁止重复上报累计值')
                return old
            m['usage'] = u
            m['body'] = body or f'报告本次调用 token：输入 {u["input"]}，输出 {u["output"]}。'
        for k in ('task', 'verdict', 'kind', 'availability', 'reply_to', 'request_id',
                  'summary', 'result', 'verification', 'blockers', 'reviewer', 'stage', 'integration_plan'):
            if payload.get(k) is not None: m[k] = payload[k]
        if files: m['files'] = files
        if typ == 'task' and kind: m['kind'] = kind
        if typ == 'task' and deps: m['depends_on'] = deps
        if attachments: m['attachments'] = attachments
        result = append(m)
        if not human and who in cfg['agents']: touch(sid, who)
        return result

def session_action(data):
    with transaction():
        cfg, msgs = config(), load()
        request_id = data.get('request_id')
        request_hash = None
        if request_id is not None:
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', request_id): raise Reject('无效请求编号')
            request_hash = hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != 'request_id'}, sort_keys=True).encode()).hexdigest()
            previous = next((m for m in msgs if m.get('session_request_id') == request_id), None)
            if previous:
                if previous.get('request_hash') != request_hash: raise Reject('此请求编号已用于不同操作，请刷新并核对状态')
                return {'session': previous['session'], **({'instance': previous['instance']['id']} if previous['type'] == 'instance' else {})}
        def emit(event):
            if request_id is not None: event.update(session_request_id=request_id, request_hash=request_hash)
            return append(event)
        action = data.get('action')
        if action == 'create':
            title = data.get('title', '').strip()
            mode = data.get('mode', 'leader')
            if not title or len(title) > 120: raise Reject('会话名称需要 1 至 120 字符')
            if mode not in ('leader', 'roundtable'): raise Reject('无效模式')
            shared = data.get('shared_context', cfg.get('shared_context', False))
            if type(shared) is not bool: raise Reject('全局协作上下文必须为布尔值')
            members = participants(data.get('participants', cfg.get('participants', ['claude', 'codex', 'reasonix'])), cfg, cfg['lead'])
            sid = uuid.uuid4().hex[:12]
            emit({'session': sid, 'from': 'human', 'to': ['all'], 'type': 'session',
                    'body': title, 'mode': mode, 'lead': cfg['lead'], 'shared_context': shared, 'participants': members})
            return {'session': sid}
        sid = data.get('session')
        st = derive(msgs, cfg, sid)
        if st['session']['status'] == 'ended': raise Reject('已结束会话不可修改')
        base_cfg = cfg
        cfg = {**cfg, 'agents': st['agents']}
        if action in ('instance_create', 'instance_update'):
            if type(data.get('expected_revision')) is not int or data['expected_revision'] != st['session']['instance_revision']:
                raise Reject('实例或参与设置已变化，请刷新实例列表后重试')
            creating = action == 'instance_create'
            if creating:
                client = data.get('client')
                if not isinstance(client, str) or client not in base_cfg['agents']: raise Reject('请选择有效客户端类型')
                if len(st['agents']) >= 32: raise Reject('单会话最多登记 32 个实例，停用仍保留记录；更多实例请新建会话')
                aid = client + '-' + uuid.uuid4().hex[:12]
                if any(aid in s.get('instances', {}) for s in sessions(msgs, base_cfg).values()): raise Reject('实例编号冲突，请重试')
            else:
                aid = data.get('instance')
                if not isinstance(aid, str) or aid not in st['agents']: raise Reject('实例不存在于当前会话')
                client = client_of(st['agents'], aid)
                if 'client' in data and data['client'] != client: raise Reject('实例客户端类型不可更换，请新建实例')
            role = data.get('role')
            if role not in ('lead', 'worker', 'reviewer'): raise Reject('角色需要 lead / worker / reviewer')
            fields = {}
            for key, maximum in (('name', 60), ('model', 100)):
                value = data.get(key, '')
                if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
                    raise Reject(f'{key} 需要不超过 {maximum} 字符的单行文本')
                fields[key] = value.strip()
            if not fields['name']: raise Reject('请输入实例名称，便于区分窗口')
            if not creating and aid == st['lead'] and role != 'lead': raise Reject('请先选择其他主导实例，再调整原主导角色')
            # Registry edits do not impersonate joins or start external clients.
            instance = {'id': aid, 'client': client, **fields, 'role': 'reviewer' if role == 'reviewer' else 'worker'}
            event = {'session': sid, 'from': 'human', 'to': ['all'], 'type': 'instance', 'instance': instance,
                     'body': f'{"新增" if creating else "更新"}协作实例：{fields["name"]}（{aid}），客户端 {client}，模型标注 {fields["model"] or "未填写"}，角色 {role}。模型需在客户端实际选择；并发窗口各用独立实例编号。'}
            if creating or role == 'lead': event['participants'] = list(dict.fromkeys([*st['session']['participants'], aid]))
            if role == 'lead': event['lead'] = aid
            emit(event)
            return {'session': sid, 'instance': aid}
        if action in ('paused', 'active', 'ended'):
            if action == st['session']['status']: return {'session': sid}
            emit({'session': sid, 'from': 'human', 'to': ['all'], 'type': 'control',
                    'action': action, 'body': {'paused': '暂停协作：完成当前安全步骤后停止写入，确认收到。',
                    'active': '恢复协作：先确认最新需求，再继续任务。', 'ended': '结束会话：停止新工作，释放文件占用并确认。'}[action]})
        elif action == 'settings':
            mode, lead = data.get('mode', st['mode']), data.get('lead', st['lead'])
            shared = data.get('shared_context', st['session']['shared_context'])
            if type(shared) is not bool: raise Reject('全局协作上下文必须为布尔值')
            if mode not in ('leader', 'roundtable') or lead not in cfg['agents']: raise Reject('模式或主管无效')
            members = participants(data.get('participants', st['session']['participants']), cfg, lead)
            emit({'session': sid, 'from': 'human', 'to': ['all'], 'type': 'settings',
                    'mode': mode, 'lead': lead, 'shared_context': shared, 'participants': members,
                    'body': f'协作设置更新：{mode}，主导成员 {lead}，参与成员 {", ".join(members)}，全局协作上下文 {"开启" if shared else "关闭"}。按新范围重读摘要，未参与成员停止新工作并释放占用。'})
        elif action == 'reassign':
            task = next((t for t in st['tasks'] if t['id'] == data.get('task')), None)
            target = data.get('to')
            if not task or task['state'] not in ('待办', '受阻', '被打回'): raise Reject('仅待办、受阻或被打回的任务可转交')
            if target not in st['session']['participants']: raise Reject('接收者必须是参与成员')
            if target == task.get('reviewer'): raise Reject('接收者是预定验收人，请让主导先调整 reviewer，避免自审')
            if (task.get('kind') or media_intent(task['body'])) and client_of(cfg['agents'], target) not in ('codex', 'claude'): raise Reject('媒体任务只允许 Codex 或 Claude 实例执行')
            if any(owns(owner, task['owner'], sid) for owner in st['locks'].values()):
                raise Reject('原负责人仍持有文件占用，请先确认停止并释放')
            emit({'session': sid, 'from': 'human', 'to': [target], 'type': 'reassign', 'task': task['id'],
                    'body': f'任务由 {task["owner"]} 转交给 {target}；请重新认领并核对范围。'})
        else: raise Reject('未知会话操作')
        return {'session': sid}

def read_state(sid=None, limit=300):
    with transaction():
        cfg, msgs = config(), load()
        ss = sessions(msgs, cfg)
        sid = sid or list(ss)[-1]
        st = derive(msgs, cfg, sid)
        st['receipts'] = {}
        for m in st['messages']:
            if m['type'] == 'ack':
                st['receipts'].setdefault(m['reply_to'], []).append(m['from'])
        st['messages'] = st['messages'][-limit:]
        st.update({'csrf': TOKEN, 'app': 'agents-talk', 'version': 2, 'app_version': VERSION,
                   'root': str(ROOT), 'server_time': now(), 'revision': len(msgs)})
        all_agents = session_agents(cfg, {})
        for s in ss.values():
            all_agents.update({aid: a for aid, a in session_agents(cfg, s).items() if aid not in cfg['agents']})
        st['clients'] = cfg['agents']
        st['usage_agents_all_sessions'] = all_agents
        st['token_usage_all_sessions'] = token_usage(msgs, {'agents': all_agents})
        st['token_usage_clients_all_sessions'] = usage_by_client(msgs, all_agents, cfg)
        return st

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send(self, code, payload, mime='application/json; charset=utf-8', headers=None):
        if not isinstance(payload, bytes): payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        for key, val in {'Content-Type': mime, 'Content-Length': str(len(payload)),
                         'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                         'X-Frame-Options': 'DENY', **(headers or {})}.items(): self.send_header(key, val)
        self.end_headers()
        try: self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
    def guard(self, write=False):
        port = self.server.server_port
        hosts = (f'127.0.0.1:{port}', f'localhost:{port}')
        if self.headers.get('Host') not in hosts: raise Reject('仅允许本机访问')
        origin = self.headers.get('Origin')
        if origin and origin not in ['http://' + h for h in hosts]: raise Reject('跨来源请求被拒绝')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site': raise Reject('跨站请求被拒绝')
        if write and self.headers.get('X-Agents-Token') != TOKEN: raise Reject('页面凭证失效，请刷新页面')
    def do_GET(self):
        try:
            self.guard()
            url = urlsplit(self.path); q = parse_qs(url.query); path = url.path
            sid = q.get('session', [None])[0]
            if path == '/api/health':
                config()
                self.send(200, {'app': 'agents-talk', 'version': 2, 'app_version': VERSION,
                               'root': str(ROOT), 'data': str(DATA), 'config': str(CONFIG),
                               'pid': os.getpid(), 'status': 'ok'})
            elif path == '/api/state':
                limit = min(10000, max(1, int(q.get('limit', ['300'])[0])))
                self.send(200, read_state(sid, limit))
            elif path == '/api/context':
                aid = q.get('agent', [''])[0]
                with transaction():
                    msgs = load(); cfg = config()
                    st = derive(msgs, cfg, sid or list(sessions(msgs, cfg))[-1])
                    self.send(200, agent_context(st, aid,
                        since=int(q.get('since', ['-1'])[0]), task_id=q.get('task', [None])[0],
                        offset=max(0, int(q.get('offset', ['0'])[0])),
                        task_limit=min(100, max(1, int(q.get('limit', ['30'])[0])))))
            elif path == '/api/skills':
                state = read_state(sid); current = state['session']; sid = current['id']
                instructions = {}
                import shlex
                import subprocess
                command = [sys.executable, str(ROOT / 'hub.py'), '--data-dir', str(DATA)]
                actual_config = CONFIG if CONFIG.exists() or CONFIG != ROOT / 'config.json' else ROOT / 'config.example.json'
                command.extend(['--config', str(actual_config)])
                prefix = subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command)
                for aid, actor in state['agents'].items():
                    client = actor['client']
                    role = '主导者' if aid == current['lead'] else '验收者' if actor['role'] == 'reviewer' else '协同者'
                    instructions[aid] = f'在 {client} 的独立对话窗口调用 agents-talk skill，以实例 {aid} 加入看板会话 {sid}。\n实例名称：{actor["name"]}；职责：{role}；模型标注：{actor["model"] or "未填写"}。模型需你在当前客户端选择并确认，面板不切换模型。\n项目路径：{ROOT}\n如果客户端未发现 skill，请读取 {ROOT / "skills" / "agents-talk" / "SKILL.md"} 并执行。\n先读协议，再 read --agent {aid} --session {sid} 核对 identity.client 与当前客户端一致，然后用 --from {aid} 报到。所有读写、监听、用量和文件占用固定使用此实例编号，不退回通用 {client} 编号，不复用其他窗口的实例。'
                    instructions[aid] += '\n重新接入时读取最新 skill 与协议，保留历史和任务，通过 listen --timeout 50 持续协作，按 continuation 行动。正常超时继续等待；用户停止或运行限制优先。'
                    instructions[aid] += f'\n本看板命令前缀：{prefix}\n全部子命令须保留此前缀中的状态目录与配置参数，避免接入另一份看板数据。'
                    if client == 'claude': instructions[aid] += f'\nClaude 的原生 Stop 提醒需通过 /agents-talk 加载安装版，再 bind --agent {aid} --session {sid} --client-session <当前真实原生会话ID>；每个原生窗口绑定独立实例，仅手动读取项目副本无法注册 hook。'
                    if aid not in current['participants']:
                        instructions[aid] = f'{aid} 未参与此会话。需要使用时先在面板「参与成员」中启用，再复制接入说明。'
                self.send(200, instructions)
            elif path == '/api/export':
                with transaction():
                    msgs = load(); st = derive(msgs, config(), sid or list(sessions(msgs, config()))[-1])
                if q.get('format', ['json'])[0] == 'md':
                    txt = '# ' + st['session']['title'] + '\n\n'
                    for m in st['messages']:
                        txt += f'## {m["ts"]} · {m.get("from")} · {m["type"]}\n\n{m.get("body", "")}\n\n'
                        for a in m.get('attachments', []): txt += f'附件：{a["name"]}（本地路径 {a["path"]}）\n\n'
                    self.send(200, txt.encode('utf-8'), 'text/markdown; charset=utf-8')
                else: self.send(200, st)
            elif path == '/guide':
                txt = '\n\n'.join((ROOT / f).read_text(encoding='utf-8') for f in ('README.md', 'PROTOCOL.md'))
                page = '<!doctype html><meta charset="utf-8"><title>Agents Talk 使用说明</title><link rel="stylesheet" href="/style.css"><main class="guide"><a href="/">返回面板</a><pre>' + html.escape(txt) + '</pre></main>'
                self.send(200, page.encode('utf-8'), 'text/html; charset=utf-8')
            elif path.startswith('/media/'):
                a = attachment(path.split('/')[-1]); content = (DATA / 'uploads' / (a['id'] + '.bin')).read_bytes()
                headers = {} if a['mime'] != 'application/octet-stream' else {'Content-Disposition': 'attachment; filename="attachment.bin"'}
                self.send(200, content, a['mime'], headers)
            elif path in ('/', '/index.html', '/style.css', '/observatory.css', '/app.js'):
                name = 'index.html' if path == '/' else path[1:]
                mime = {'index.html': 'text/html', 'style.css': 'text/css', 'observatory.css': 'text/css', 'app.js': 'text/javascript'}[name]
                self.send(200, (ROOT / 'web' / name).read_bytes(), mime + '; charset=utf-8',
                          {'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            else: self.send(404, {'error': 'not found'})
        except (Reject, ValueError) as e: self.send(400, {'error': str(e)})
        except OSError as e: self.send(500, {'error': '本地文件读取失败：' + str(e)})
    def do_POST(self):
        try:
            self.guard(True)
            url = urlsplit(self.path)
            size = int(self.headers.get('Content-Length', '0'))
            max_size = MAX_UPLOAD if url.path == '/api/upload' else 1024 * 1024
            if not 0 < size <= max_size: raise Reject('请求为空或超过大小限制')
            self.connection.settimeout(30)
            raw = self.rfile.read(size)
            if len(raw) != size: raise Reject('上传未完成，请重试')
            if url.path == '/api/upload':
                name = parse_qs(url.query).get('name', ['attachment'])[0]
                result = save_attachment(name, raw)
            else:
                data = json.loads(raw)
                if not isinstance(data, dict): raise Reject('请求必须是 JSON 对象')
                if url.path == '/api/post': result = post(data, human=True)
                elif url.path == '/api/session': result = session_action(data)
                else: self.send(404, {'error': 'not found'}); return
            self.send(200, result)
        except (Reject, ValueError, TypeError, AttributeError) as e: self.send(400, {'error': str(e)})
        except OSError as e: self.send(500, {'error': '本地写入失败：' + str(e)})

def main():
    global DATA, BOARD, CONFIG
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Agents Talk 本地协作工作室')
    parser.add_argument('--version', action='version', version='Agents Talk ' + VERSION)
    parser.add_argument('--data-dir', type=Path, help='状态目录，全部客户端须使用相同目录')
    parser.add_argument('--config', type=Path, help='自定义配置文件，全部客户端须使用相同文件')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('post', help='发布消息')
    p.add_argument('--from', dest='sender', required=True)
    p.add_argument('--session', required=True)
    p.add_argument('--type', choices=TYPES, required=True)
    for flag in ('to', 'body', 'body-file', 'task', 'files', 'verdict', 'kind', 'availability', 'reply-to', 'request-id',
                 'summary', 'result', 'verification', 'blockers', 'usage-id', 'provider', 'model', 'usage-source', 'depends-on',
                 'reviewer', 'stage', 'integration-plan'):
        p.add_argument('--' + flag)
    for flag in ('input-tokens', 'output-tokens', 'cached-input-tokens', 'reasoning-output-tokens'):
        p.add_argument('--' + flag, type=int)
    p.add_argument('--task-revision', type=int, help='任务文件占用需传入刚读取的 tasks[].revision')
    p.add_argument('--attach', action='append', default=[], help='附加本地文件，可重复，单个最大 32 MB')
    for name in ('read', 'wait', 'listen', 'status', 'tasks', 'sessions'):
        p = sub.add_parser(name)
        p.add_argument('--session'); p.add_argument('--agent'); p.add_argument('--task')
        p.add_argument('--tail', type=int, default=0, help='仅显示末尾 N 条；不会推进 wait 游标')
        p.add_argument('--since', type=int, default=-1)
        p.add_argument('--context-since', type=int, default=-1, help='只返回此版本之后变化的任务摘要和消息')
        p.add_argument('--task-offset', type=int, default=0, help='任务摘要分页起点')
        p.add_argument('--task-limit', type=int, default=30, help='每页任务数，最大 100')
        p.add_argument('--full', action='store_true', help='按当前范围读取完整正文，建议配合 --task 或 --message')
        p.add_argument('--message', help='按消息 ID 读取完整正文')
        p.add_argument('--timeout', type=int, default=50)
        p.add_argument('--poll', type=float, default=1)
    p = sub.add_parser('serve'); p.add_argument('--port', type=int, default=8765); p.add_argument('--no-open', action='store_true')
    p = sub.add_parser('reset', help='保留全部历史并创建新会话'); p.add_argument('--title', default='新协作')
    p = sub.add_parser('bind', help='绑定 Claude 原生会话的 Stop 防提前结束提醒')
    p.add_argument('--session', required=True); p.add_argument('--agent', required=True)
    p.add_argument('--client-session', required=True); p.add_argument('--detach', action='store_true')
    sub.add_parser('stop-hook', help='Claude Stop hook，读取标准输入 JSON')
    sub.add_parser('init', help='创建默认本地配置及 workspace，不覆盖已有文件')
    sub.add_parser('doctor', help='只读诊断环境、配置、日志和资源，不接入会话')
    args = parser.parse_args()
    if args.data_dir: DATA = args.data_dir.resolve(); BOARD = DATA / 'board.jsonl'
    if args.config:
        CONFIG = args.config.resolve()
        os.environ['AGENTS_TALK_CONFIG'] = str(CONFIG)
    stack = contextlib.ExitStack()
    try:
        if args.cmd == 'doctor':
            from scripts.project_tools import diagnose
            result = diagnose(sys.modules[__name__])
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 2
        if args.cmd == 'init':
            if not CONFIG.exists():
                CONFIG.parent.mkdir(parents=True, exist_ok=True)
                with CONFIG.open('x', encoding='utf-8') as f:
                    f.write((ROOT / 'config.example.json').read_text(encoding='utf-8'))
            config()
            DATA.mkdir(parents=True, exist_ok=True)
            (ROOT / 'workspace').mkdir(exist_ok=True)
            print(json.dumps({'config': str(CONFIG), 'data': str(DATA), 'workspace': str(ROOT / 'workspace')}, ensure_ascii=False))
            return 0
        if args.cmd == 'serve':
            config()
            if not 1 <= args.port <= 65535: raise Reject('端口须介于 1 和 65535')
            DATA.mkdir(parents=True, exist_ok=True)
            (ROOT / 'workspace').mkdir(exist_ok=True)
            srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
            srv.daemon_threads = True
            print(f'Agents Talk http://127.0.0.1:{args.port}/', flush=True)
            if not args.no_open: webbrowser.open(f'http://127.0.0.1:{args.port}/')
            try: srv.serve_forever()
            except KeyboardInterrupt: pass
            finally: srv.server_close()
            return
        if args.cmd == 'stop-hook':
            try: result = stop_guard(json.load(sys.stdin))
            except (Reject, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                print('Agents Talk Stop guard unavailable: ' + str(e), file=sys.stderr)
                result = {}  # Fail open: guard errors must not trap the user in a turn.
        elif args.cmd == 'bind': result = bind_client(args.session, args.agent, args.client_session, args.detach)
        elif args.cmd == 'reset': result = session_action({'action': 'create', 'title': args.title})
        elif args.cmd == 'post':
            data = {k: v for k, v in vars(args).items() if v is not None}
            data['from'] = data.pop('sender')
            if args.body_file: data['body'] = sys.stdin.read() if args.body_file == '-' else Path(args.body_file).read_text(encoding='utf-8-sig')
            data['attachments'] = []
            for f in args.attach:
                path = Path(f)
                if path.stat().st_size > MAX_UPLOAD: raise Reject('附件超过 32 MB')
                data['attachments'].append(save_attachment(path.name, path.read_bytes())['id'])
            result = post(data)
        else:
            waiting = args.cmd in ('wait', 'listen')
            if waiting and (not args.agent or not args.session): raise Reject('wait/listen 需要 --agent 和 --session')
            if waiting and (args.task or args.message or args.since != -1 or args.context_since != -1):
                raise Reject('wait 使用专属游标；定向或增量查询请用 read，避免跳过未读消息')
            if args.task_offset < 0 or not 1 <= args.task_limit <= 100: raise Reject('任务分页范围无效')
            if waiting:
                with transaction():
                    cfg = config(); known_sessions = sessions(load(), cfg)
                    if args.session not in known_sessions or args.agent not in session_agents(cfg, known_sessions[args.session]):
                        raise Reject('监听需要有效的成员和会话')
                stack.enter_context(listener_slot(args.session, args.agent))
            deadline = time.monotonic() + max(1, min(args.timeout, 60))
            while True:
                with transaction():
                    cfg, msgs = config(), load()
                    ss = sessions(msgs, cfg)
                    sid = args.session or list(ss)[-1]
                    if sid not in ss: raise Reject('会话不存在')
                    if args.agent and args.agent not in session_agents(cfg, ss[sid]): raise Reject('当前会话不存在此 agent 实例')
                    if args.agent and args.cmd != 'sessions' and sid in ss: touch(sid, args.agent, reading=True)
                    result = derive(msgs, cfg, sid)
                    if args.agent and args.cmd != 'sessions':
                        since = max(args.context_since, args.since)
                        feed = None
                        if waiting:
                            directory = DATA / '.seen'; directory.mkdir(exist_ok=True)
                            cursor = directory / f'{sid}.{args.agent}.txt'
                            since = int(cursor.read_text()) if cursor.exists() else -1
                            _, scoped = agent_scope(result, args.agent)
                            unread = [m for m in scoped if m['_i'] > since and m.get('from') != args.agent]
                            feed = unread[:min(100, args.tail if args.tail > 0 else 20)]
                        result = agent_context(result, args.agent, since=since, task_id=args.task,
                            offset=args.task_offset, task_limit=args.task_limit,
                            message_limit=min(100, args.tail if args.tail > 0 else 20),
                            full=args.full, message_id=args.message, feed=feed)
                        if waiting:
                            result['context']['unread_remaining'] = len(unread) - len(feed)
                            if feed: cursor.write_text(str(feed[-1]['_i']))
                        else:
                            feed = result['messages']
                        if args.cmd in ('tasks', 'status'): result.pop('messages')
                    else:
                        feed = [m for m in result['messages'] if m['_i'] > args.since and (not args.task or m.get('task') == args.task)]
                        result['messages'] = feed[-args.tail:] if args.tail > 0 else feed
                        if args.cmd == 'sessions': result = list(ss.values())
                        elif args.cmd == 'tasks': result = [t for t in result['tasks'] if not args.task or t['id'] == args.task]
                        elif args.cmd == 'status': result.pop('messages')
                if not waiting or feed or result.get('pending_interventions') or result['session']['status'] == 'ended' or not result.get('participation', {}).get('enabled', True): break
                if args.cmd == 'listen' and result['continuation']['action'] in ('execute', 'exit'): break
                if time.monotonic() >= deadline:
                    if args.cmd == 'listen':
                        result = {k: result[k] for k in ('session', 'agent', 'continuation', 'pending_interventions', 'team_health') if k in result}
                        result['session'] = {k: v for k, v in result['session'].items() if k != 'instances'}
                        result['timeout'] = True
                        break
                    print(json.dumps({'timeout': True, 'session': sid}, ensure_ascii=False)); return 3
                time.sleep(max(.1, min(args.poll, 5)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Reject, OSError, ValueError) as e:
        print('[错误] ' + str(e), file=sys.stderr); return 2
    finally:
        stack.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
