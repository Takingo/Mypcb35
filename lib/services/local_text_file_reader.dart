import 'local_text_file_reader_stub.dart'
    if (dart.library.io) 'local_text_file_reader_io.dart';

Future<List<int>> readLocalTextFileBytes(String path) {
  return readLocalTextFileBytesImpl(path);
}
