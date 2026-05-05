import socket
import json

class RemoteJDBWrapper():
    def __init__(self, proj, bug_num, target_test = None, host='', port=13377):
        self._proj = proj
        self._bug_num = bug_num
        self._target_test = target_test
        self._host = host
        self._port = port
    
    def _relay_command(self, jdb_cmd):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self._host, self._port))
            s.sendall(json.dumps({
                'proj': self._proj,
                'bug_id': self._bug_num,
                'test_name': self._target_test,
                'jdb_cmd': jdb_cmd
            }).encode())
            data = json.loads(s.recv(1024).decode('utf-8'))
        return data['response']
    
    def terminate(self):
        pass # only to imitate JDBWrapper

if __name__ == '__main__':
    remote_jdbw = RemoteJDBWrapper('Chart', 1, 'org.jfree.chart.renderer.category.junit.AbstractCategoryItemRendererTests::test2947660')
    remote_answ = remote_jdbw._relay_command('stop at org.jfree.chart.renderer.category.AbstractCategoryItemRenderer:1797 ; run ; print dataset')
    print(remote_answ)
            
