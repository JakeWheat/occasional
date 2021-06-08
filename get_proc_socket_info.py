"""x

read /proc file system to get some info on sockets per process

TODO:
returns info for unix and tcp sockets

instead of getting the pids, just list each socket as a connection or
listen, don't really need the ports either
  this additional information is useful for troubleshooting bugs,
  but not for the basic test operation

"""
import socket
import os
import re
import glob

socket_type = socket.AF_INET
#socket_type = socket.AF_UNIX


##############################################################################

# get socket info

# reads the proc file system and returns the socket connection info
# it's not tested with non local sockets, will probably break if you have them
# when this is needed, it can be updated to support these also

# read /proc/net/tcp, and return tuples with the inode, port and
# other port parsed from the output
def read_proc_tcp():
    ret = []
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
            ps = get_port(line[2])
            pt = get_port(line[3])
            inode = line[10]
            ret.append({'inode': int(inode),
                        'port': int(ps),
                        'other_port': int(pt)})
                        
    return ret
   
# read all the socket entries from the process's /proc/X/fd dir
# returns the inode for each of the socket entries
def get_proc_socket_inodes(pid):
    ret = []
    try:
        # list the files and get the sockets
        fdd = f"/proc/{pid}/fd"
        for i in os.listdir(fdd):
            try:
                x = os.readlink(os.path.join(fdd, i))
                if x.startswith("socket:["):
                    inode = x[8:-1]
                    ret.append({'pid':int(pid),
                                'inode':int(inode)})
            except FileNotFoundError:
                pass
    except PermissionError:
        pass
    except FileNotFoundError:
        pass
    return ret

# read all the /proc/X/fds that are accessible
# and return all the sockets ((pid,inode) rows)
def get_all_proc_socket_inodes():
    global proc_fd_sockets_cache
    proc_fd_sockets_cache = []
    ret = []
    for i in glob.glob("/proc/[0-9]*"):
        pid = i[6:]
        ret = ret + get_proc_socket_inodes(pid)
    return ret

"""

returns all the sockets that pid is listening on with the port
plus all the socket connections, for these it gives the local port,
the other end port and the other end pid

it's not very race friendly, and in additional to probably breaking
if you have non local machine socket connections, it will probably
break on self socket connections, or if it's possible to copy sockets
so there is more than one socket with the same inode at one or both
ends of the socket

these limitations should be fixable if/when they come up

"""

def get_tcp_socket_info(pid):
    #print(f"get socket info 2 {pid}")
    socket_inodes = get_proc_socket_inodes(pid)
    # print("socket_inodes")
    # for i in socket_inodes:
    #     print(i)

    inode_ports = read_proc_tcp()
    socket_both_ports = []
    ret = []
    for si in socket_inodes:
        sip = next(filter(lambda ip: ip['inode'] == si['inode'], inode_ports), None)
        if sip:
            if sip['other_port'] == 0:
                ret.append({'pid':si['pid'],
                            'port':sip['port'],
                            'type':"listen"})
            else:
                socket_both_ports.append({'pid':si['pid'],
                                          'port':sip['port'],
                                          'other_port':sip['other_port']})
    # print("listeners")
    # for i in ret:
    #     print(i)

    # print("socket both ports")
    # for i in socket_both_ports:
    #     print(i)

    socket_other_inodes = []
    for sb in socket_both_ports:
        sip = next(filter(lambda ip: ip['port'] == sb['other_port'], inode_ports), None)
        if sip:
            socket_other_inodes.append({'pid': sb['pid'],
                                        'port': sb['port'],
                                        'other_port': sb['other_port'],
                                        'other_inode': sip['inode']})
    # print("socket other inode")
    # for i in socket_other_inodes:
    #     print(i)

    all_socket_inodes = get_all_proc_socket_inodes()

    # print("connections")
    for soi in socket_other_inodes:
        m = next(filter(lambda si: si['inode'] == soi['other_inode'], all_socket_inodes),None)
        r = {'pid':soi['pid'],
             'port': soi['port'],
             'other_port': soi['other_port']}
        if m is None:
            r['other_pid'] = None
        else:
            r['other_pid'] = m['pid']
        
        r['type']="connection"
        # print(r)
        ret.append(r)

    # print("done")
    
    return ret



def get_unix_socket_info(pid):
    # todo
    return []

"""

unix sockets:
get the same socket thing under /proc/N/fd
  with an inode
look in /proc/net/unix for this inode in the 7th column
the 8th column will be the path for the socket



"""

def get_socket_info(pid):
    if socket_type == socket.AF_INET:
        return get_tcp_socket_info(pid)
    elif socket_type == socket.AF_UNIX:
        return get_unix_socket_info(pid)
    else:
        raise Exception("unsupported socket type {socket_type}")


##############################################################################

# tests

"""x

TODO:

create example outputs for each of the proc reads
then add tests which read these and produce the right results

do it for listen, connected, and for unix and tcp sockets

do variations with the race conditions with a connection disappearing
or appearing in between reads of different procs
-> to document what happens, and make sure it's reasonable

get some sample output when connected to remote connection either as
the server or client, then can check these work nice

do simple full tests - check the non mocked proc read
create a process with no connections and check
start a network server (both flavours), check
then connect with a client, check both


design a proper api:

the testing isn't trying to tell which process is connected to which

since wrote the code for this, could add some tests for this sort of thing
just to keep the code and not bitrot it - it might be useful for some
troubleshooting utils later


"""
