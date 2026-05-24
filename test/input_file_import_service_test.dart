import 'package:flutter_test/flutter_test.dart';
import 'package:omnicircuit_ai/services/input_file_import_service.dart';

void main() {
  test(
    'InputFileImportService imports BOM content from a Windows path',
    () async {
      final service = InputFileImportService();

      final imported = await service.importFromPath(
        path: r'C:\Mypcb\BOM.csv',
        allowedExtensions: InputFileImportService.bomExtensions,
      );

      expect(imported.fileName, 'BOM.csv');
      expect(imported.extension, 'csv');
      expect(imported.content, contains('ESP32'));
    },
  );

  test('InputFileImportService rejects unsupported extensions', () async {
    final service = InputFileImportService();

    expect(
      () => service.importFromPath(
        path: r'C:\Mypcb\board.xlsx',
        allowedExtensions: InputFileImportService.bomExtensions,
      ),
      throwsA(isA<FileImportException>()),
    );
  });
}
