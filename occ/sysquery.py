#!/usr/bin/env python3

# todo: review the code for races, since reading proc in bulk is not
# transactional, mostly want to return null for rows where can't get
# all the info, make sure to silently skip stuff don't have permissions
# for

import occ.sck as sck
import os

import duckdb
import pandas
import time
import re
import itertools
import glob
import subprocess
import math

import logging
logger = logging.getLogger(__name__)

##############################################################################

# utils

def readfile(fn):
    #print(f"readfile {fn}")
    with open(fn) as f:
        return f.read()

def find_nth(haystack, needle, n):
    start = haystack.find(needle)
    while start >= 0 and n > 1:
        start = haystack.find(needle, start+len(needle))
        n -= 1
    return start

def run_statement(con, catalog, statement):
    for i in catalog:
        con.register(i[0], i[1])
    return con.execute(statement).fetchdf()

##############################################################################

# querying the kernel/system
# these functions return single items or iterables

def process_name(pid):
    if pid == 0:
        pid = os.getpid()
    return readfile(f"/proc/{pid}/cmdline")

socket_re = re.compile(r'socket:\[([0-9]+)\]')

# get fd info for a single pid as iterator
def fdinfo(pid):
    #print(f"get_finfo {pid}")
    fdd = f"/proc/{pid}/fd/"
    def inf(fn):
        try:
            x = os.readlink(os.path.join(fdd, fn))
            m = socket_re.match(x)
            if m:
                return (int(pid), int(fn), None, int(m[1]))
            else:
                return (int(pid), int(fn), x, None)
        except Exception as e:
            #print(e)
            return None # (fn, "scarpered")
    try:        
        return filter(None, [inf(fn) for fn in os.listdir(fdd)])
    except PermissionError:
        return iter([])


# return dataframe for fdinfo for arg
# arg can be a list of pids, a pid, or "all" to get info for all the
# readable processes
def fdinfos(pids):
    # todo: implement version that gets this for all readable processes
    return itertools.chain(*[fdinfo(pid) for pid in pids])

def fdinfos_df(pids):
    return pandas.DataFrame(fdinfos(pids), columns = ['pid','fileno', 'path', 'socket_inode'])

def pids_in_group(pgid):
    if pgid == 0:
        pgid = os.getpgid(0)
    for f in glob.glob("/proc/[0-9]*"):
        # print(f"check {f}")
        try:
            with open(f"{f}/stat") as st:
                txt = st.read()
            # 3rd field after the last occurrence of a )
            # fuck me
            last_paren = txt.rfind(')')
            t = txt[last_paren:]
            #print(f"a:{t}")
            fld = find_nth(t, ' ', 3) + 1
            t1 = t[fld:]
            #print(f"b:{t1}")
            efld = t1.find(' ')
            t2 = t1[0:efld]
            #print(f"c:'{t2}'")
            if int(t2) == int(pgid):
                yield int(f[6:])
            
        except Exception as e:
            print(e)
            pass

def process_names(pids):
    return [(pid,process_name(pid)) for pid in pids]

def process_names_df(pids):
    return pandas.DataFrame(process_names(pids),columns = ['pid', 'process_name'])


def proc_net_tcp():
    def get_port(s):
        #'00000000:008B'
        # take the last 4 digits
        # parse as a hex number to get the port
        return int(s[-4:], 16)

    with open ("/proc/net/tcp", "r") as rd:
        first = True
        for line in rd:
            #print(line,end="")
            if first:
                first = False
                continue
            line = re.split('\s+', line)
            source_port = get_port(line[2])
            target_port = get_port(line[3])
            inode = line[10]
            yield (int(inode),int(source_port), int(target_port))

def proc_net_tcp_df():
    return pandas.DataFrame(proc_net_tcp(), columns = ['inode', 'source_port', 'target_port'])

            
def proc_net_unix():
    first = True
    with open ("/proc/net/unix", "r") as rd:
        for line in rd:
            if first:
                first = False
                continue
            line = re.split('\s+', line)
            num = line[0]
            inode = line[6]
            path = line[7] if len(line) > 7 else None
            yield (num,int(inode),path)

def proc_net_unix_df():
    return pandas.DataFrame(proc_net_unix(), columns = ['num', 'inode', 'path'])

"""
TODO: use direct code instead of running ss

https://man7.org/linux/man-pages/man7/sock_diag.7.html
...

"""
def socket_connections():
    for line in subprocess.getoutput('ss -xpOH').splitlines():
        line = re.split('\s+', line)
        pid_start = line[8].rfind('pid=')
        if pid_start == -1:
            pid = None
        else:
            re.match('pid=\(\d+\)', line[8][pid_start:])
            pid = re.match('pid=(\d+)', line[8][pid_start:])[1]
        yield(pid,int(line[5]),int(line[7]))

def unix_socket_connections_df():
    return pandas.DataFrame(socket_connections(), columns = ['pid', 'inode1', 'inode2'])

# what a bunch of amateur hour shite
def unfuck(x):
    if type(x) is float:
        if math.isnan(x):
            return "None"
    return x


# not sure if creating a duckdb is slow enough for this to be worth it
def get_shared_con():
    global _shared_con
    # should be thread local if use threads
    try:
        if _shared_con is None:
            _shared_con = duckdb.connect(database=':memory:', read_only=False)
    except NameError:
        _shared_con = duckdb.connect(database=':memory:', read_only=False)
    return _shared_con

def socket_stuff(pid):
    #con = duckdb.connect(database=':memory:', read_only=False)
    con = get_shared_con()

    cat = [("fileno", fdinfos_df([pid])),
           ("proc_net_tcp", proc_net_tcp_df()),
           ("proc_net_unix", proc_net_unix_df()),
           ("unix_connections", unix_socket_connections_df()),
           ]

    x = run_statement(con, cat, f"""
select case when source_port is null then 'unix' else 'tcp' end as flavour,
       case when source_port is not null and target_port == 0
              then 'listening'
            when source_port is not null
              then 'connected'
            when proc_net_unix.num is not null and unix_connections.inode2 is null
              then 'listening'
            when proc_net_unix.num is not null and unix_connections.inode2 is not null
              then 'connected'
       end as stuff
from fileno
left outer join proc_net_tcp
on fileno.socket_inode = proc_net_tcp.inode
left outer join proc_net_unix
on fileno.socket_inode = proc_net_unix.inode
left outer join unix_connections
on fileno.socket_inode = unix_connections.inode1
where socket_inode is not null""")
    for r in x.iterrows():
        #print(r)
        #print(f"r0 {r[0]} r1{r[1]}")
        #print(type(r))
        #print(type(r[0]))
        yield (r[1][0], unfuck(r[1][1]))
