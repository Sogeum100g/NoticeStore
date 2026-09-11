import 'package:clients/main.dart';
import 'package:clients/providers/auth_provider.dart';
import 'package:clients/providers/favorite_provider.dart';
import 'package:clients/providers/notice_provider.dart';
import 'package:clients/providers/settings_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('app boots with its required providers', (
    WidgetTester tester,
  ) async {
    dotenv.testLoad(fileInput: 'IP_ADDRESS=localhost');

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => SettingsProvider()),
          ChangeNotifierProvider(create: (_) => AuthProvider()),
          ChangeNotifierProvider(create: (_) => NoticeProvider()),
          ChangeNotifierProvider(create: (_) => FavoriteProvider()),
        ],
        child: const MyApp(),
      ),
    );

    expect(find.byType(MaterialApp), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });
}
