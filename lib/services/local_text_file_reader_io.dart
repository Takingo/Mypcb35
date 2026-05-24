import 'dart:io';

Future<List<int>> readLocalTextFileBytesImpl(String path) {
  return File(path).readAsBytes();
}
