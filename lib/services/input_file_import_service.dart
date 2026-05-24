import 'dart:convert';

import 'package:file_picker/file_picker.dart';

import 'local_text_file_reader.dart';

class InputFileImport {
  const InputFileImport({
    required this.fileName,
    required this.extension,
    required this.content,
    required this.sourcePath,
  });

  final String fileName;
  final String extension;
  final String content;
  final String? sourcePath;
}

class InputFileImportService {
  static const designExtensions = [
    'md',
    'txt',
    'csv',
    'json',
    'net',
    'xml',
    'yaml',
    'yml',
    'sch',
    'kicad_sch',
  ];

  static const bomExtensions = [
    'csv',
    'tsv',
    'txt',
    'md',
    'json',
    'xml',
    'yaml',
    'yml',
  ];

  Future<InputFileImport?> pickTextFile({
    required String dialogTitle,
    required List<String> allowedExtensions,
  }) async {
    final result = await FilePicker.pickFiles(
      dialogTitle: dialogTitle,
      type: FileType.custom,
      allowedExtensions: allowedExtensions,
      withData: false,
      allowMultiple: false,
    );
    final file = result?.files.single;
    final path = file?.path;
    if (file == null || path == null) {
      return null;
    }
    final bytes = await readLocalTextFileBytes(path);
    return InputFileImport(
      fileName: file.name,
      extension: (file.extension ?? '').toLowerCase(),
      content: _decodeText(bytes),
      sourcePath: path,
    );
  }

  Future<InputFileImport> importFromPath({
    required String path,
    required List<String> allowedExtensions,
  }) async {
    final normalizedPath = path.trim().replaceAll('"', '');
    if (normalizedPath.isEmpty) {
      throw const FileImportException('Dosya yolu bos olamaz.');
    }
    final fileName = normalizedPath.split(RegExp(r'[\\/]')).last;
    final extension = _extensionFor(fileName);
    if (!allowedExtensions.contains(extension)) {
      throw FileImportException(
        '.$extension dosya turu desteklenmiyor. Desteklenenler: ${allowedExtensions.map((item) => '.$item').join(', ')}',
      );
    }
    final bytes = await readLocalTextFileBytes(normalizedPath);
    return InputFileImport(
      fileName: fileName,
      extension: extension,
      content: _decodeText(bytes),
      sourcePath: normalizedPath,
    );
  }

  String _extensionFor(String fileName) {
    final dotIndex = fileName.lastIndexOf('.');
    if (dotIndex < 0 || dotIndex == fileName.length - 1) {
      return '';
    }
    return fileName.substring(dotIndex + 1).toLowerCase();
  }

  String _decodeText(List<int> bytes) {
    final decoded = utf8.decode(bytes, allowMalformed: true);
    return decoded.replaceFirst(RegExp(r'^\uFEFF'), '').trim();
  }
}

class FileImportException implements Exception {
  const FileImportException(this.message);

  final String message;

  @override
  String toString() => message;
}
