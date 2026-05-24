import 'dart:io';

const host = '127.0.0.1';
const port = 5174;

Future<void> main() async {
  final root = Directory('build/web');
  if (!root.existsSync()) {
    stderr.writeln('build/web does not exist. Run flutter build web first.');
    exitCode = 1;
    return;
  }

  final server = await HttpServer.bind(host, port);
  stdout.writeln('Serving OmniCircuit AI at http://$host:$port');
  await for (final request in server) {
    await _handleRequest(root, request);
  }
}

Future<void> _handleRequest(Directory root, HttpRequest request) async {
  final uriPath = Uri.decodeComponent(request.uri.path);
  final relativePath = uriPath == '/' ? 'index.html' : uriPath.substring(1);
  final file = File('${root.path}/$relativePath');
  final target = file.existsSync() ? file : File('${root.path}/index.html');

  request.response.headers.contentType = _contentType(target.path);
  await request.response.addStream(target.openRead());
  await request.response.close();
}

ContentType _contentType(String path) {
  if (path.endsWith('.html')) return ContentType.html;
  if (path.endsWith('.js')) return ContentType('application', 'javascript');
  if (path.endsWith('.json')) return ContentType.json;
  if (path.endsWith('.wasm')) return ContentType('application', 'wasm');
  if (path.endsWith('.css')) return ContentType('text', 'css');
  if (path.endsWith('.png')) return ContentType('image', 'png');
  if (path.endsWith('.svg')) return ContentType('image', 'svg+xml');
  return ContentType.binary;
}
