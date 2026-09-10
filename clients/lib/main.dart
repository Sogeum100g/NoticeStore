import 'dart:async';
import 'dart:io';
import 'package:app_links/app_links.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:clients/screens/add/add_site_screen.dart';
import 'package:clients/screens/home/home_screen.dart';
import 'package:clients/screens/subscriptions/subscriptions_screen.dart';
import 'package:provider/provider.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'firebase_options.dart';

import 'package:clients/providers/auth_provider.dart';
import 'package:clients/providers/favorite_provider.dart';
import 'package:clients/providers/notice_provider.dart';
import 'package:clients/providers/settings_provider.dart';
import 'package:clients/services/in_app_notification_service.dart';
import 'package:clients/services/notification_service.dart';
import 'package:clients/services/preferences_service.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:in_app_update/in_app_update.dart';

import 'screens/main_wrapper.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await Future.wait([
    Firebase.initializeApp(
      options: DefaultFirebaseOptions.currentPlatform,
    ),
    dotenv.load(fileName: ".env"),
    PreferencesService.init(),
  ]);

  // FCM에 접근하는 서비스이므로 Firebase 초기화 후 실행합니다.
  await NotificationService().init();

  final settingsProvider = SettingsProvider();

  settingsProvider.initSettings();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: settingsProvider),
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProvider(create: (_) => NoticeProvider()),
        ChangeNotifierProvider(create: (_) => FavoriteProvider()),
      ],
      child: const MyApp(),
    ),
  );
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  StreamSubscription? _intentMediaStreamSubscription;

  late AppLinks _appLinks;
  StreamSubscription<Uri>? _linkSubscription;

  @override
  void initState() {
    super.initState();
    _initSharingIntent();
    _initDeepLinks();
    _checkForAppUpdate();
  }

  Future<void> _checkForAppUpdate() async {
    if (kIsWeb || !Platform.isAndroid) return;

    try {
      final AppUpdateInfo info = await InAppUpdate.checkForUpdate();
      if (info.updateAvailability != UpdateAvailability.updateAvailable) {
        return;
      }
      if (!info.flexibleUpdateAllowed) return;

      await InAppUpdate.startFlexibleUpdate();
      _showUpdateReadySnackBar();
    } catch (e) {
      debugPrint("인앱 업데이트 확인 실패: $e");
    }
  }

  void _showUpdateReadySnackBar() {
    final messenger = InAppNotificationService.messengerKey.currentState;
    if (messenger == null) {
      // MaterialApp이 아직 첫 프레임을 그리기 전이면 다음 프레임에 재시도합니다.
      WidgetsBinding.instance
          .addPostFrameCallback((_) => _showUpdateReadySnackBar());
      return;
    }

    messenger.clearSnackBars();
    messenger.showSnackBar(
      SnackBar(
        content: const Text("새 버전이 준비됐어요. 지금 재시작할까요?"),
        duration: const Duration(days: 1),
        behavior: SnackBarBehavior.floating,
        action: SnackBarAction(
          label: "재시작",
          onPressed: () {
            InAppUpdate.completeFlexibleUpdate().catchError((e) {
              debugPrint("업데이트 설치 실패: $e");
            });
          },
        ),
      ),
    );
  }

  void _initDeepLinks() {
    _appLinks = AppLinks();

    _appLinks.getInitialLink().then((uri) {
      if (uri != null) _handleDeepLink(uri);
    });

    _linkSubscription = _appLinks.uriLinkStream.listen((uri) {
      _handleDeepLink(uri);
    }, onError: (err) {
      debugPrint("🔗 [AppLinks] 딥링크 에러: $err");
    });
  }

  void _handleDeepLink(Uri uri) {
    debugPrint("🔗 [AppLinks] 딥링크 수신: $uri");

    if (uri.path.contains('/invite')) {
      final referrerCode = uri.queryParameters['ref'];

      if (referrerCode != null && referrerCode.isNotEmpty) {
        debugPrint("🎁 추천인 코드 확인: $referrerCode");

        // 콜드 스타트 시 context가 null일 수 있으므로 로컬 저장소에 안전하게 보관합니다.
        PreferencesService.saveReferrerCode(referrerCode);
      }
    }
  }

  void _initSharingIntent() {
    // 모바일 환경(안드로이드, iOS)에서만 공유 인텐트 활성화
    if (!kIsWeb && (Platform.isAndroid || Platform.isIOS)) {
      _intentMediaStreamSubscription = ReceiveSharingIntent.instance
          .getMediaStream()
          .listen((List<SharedMediaFile> value) {
        if (value.isNotEmpty && value.first.type == SharedMediaType.text) {
          _handleSharedUrl(value.first.path);
        }
      }, onError: (err) {
        debugPrint("getIntentDataStream error: $err");
      });

      ReceiveSharingIntent.instance.getInitialMedia().then((List<SharedMediaFile> value) {
        if (value.isNotEmpty && value.first.type == SharedMediaType.text) {
          _handleSharedUrl(value.first.path);
          // 처리 후 인텐트 초기화 (중복 처리 방지)
          ReceiveSharingIntent.instance.reset();
        }
      });
    } else {
      // 윈도우 등 기타 환경에서는 로그만 출력하고 넘어갑니다.
      debugPrint("💻 윈도우/데스크톱 환경: receive_sharing_intent 초기화를 건너뜁니다.");
    }
  }

  void _handleSharedUrl(String url) {
    if (url.startsWith('http')) {
      final context = navigatorKey.currentContext;
      if (context != null) {
        context.read<NoticeProvider>().setPendingUrl(url);

        context.read<NoticeProvider>().setSelectedIndex(3);

        navigatorKey.currentState?.popUntil((route) => route.isFirst);
      }
    }
  }

  @override
  void dispose() {
    _intentMediaStreamSubscription?.cancel();
    _linkSubscription?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<SettingsProvider>().settings;

    return MaterialApp(
      navigatorKey: navigatorKey,
      scaffoldMessengerKey: InAppNotificationService.messengerKey,
      title: '공지저장소',
      debugShowCheckedModeBanner: false,

      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.blue,
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: Colors.white,
      ),

      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [
        Locale('ko', 'KR'),
        Locale('en', 'US'),
      ],

      home: const MainWrapper(),
    );
  }
}
