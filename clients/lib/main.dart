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
import 'firebase_options.dart'; // 💡 자동 생성된 파일 임포트

// 서비스 및 프로바이더 임포트
import 'package:clients/providers/auth_provider.dart';
import 'package:clients/providers/favorite_provider.dart';
import 'package:clients/providers/notice_provider.dart';
import 'package:clients/providers/settings_provider.dart'; // 💡 추가
import 'package:clients/services/notification_service.dart';
import 'package:clients/services/preferences_service.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import 'screens/main_wrapper.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

void main() async {
  // 1. Flutter 엔진 초기화 (비동기 작업 전 필수)
  WidgetsFlutterBinding.ensureInitialized();

  // 2. Firebase 및 환경 설정 병렬 초기화 [cite: 2026-02-15]
  // Firebase.initializeApp()을 포함하여 병렬로 처리합니다.
  await Future.wait([
    // 💡 생성된 옵션을 적용하여 초기화합니다.
    Firebase.initializeApp(
      options: DefaultFirebaseOptions.currentPlatform,
    ),
    dotenv.load(fileName: ".env"),
    PreferencesService.init(),
  ]);

  // 3. Firebase가 완료된 후 NotificationService 초기화
  // NotificationService 내부에서 FCM 토큰을 가져오거나 리스너를 달기 때문에
  // Firebase 초기화가 완료된 시점(여기)에서 호출하는 것이 안전합니다.
  await NotificationService().init();

  final settingsProvider = SettingsProvider();

  // 💡 초기화 로직을 비동기로 시작만 하고 바로 runApp으로 넘어감 (UI 즉각 반응)
  // 내부적으로 SharedPreferences 값을 읽어와서 UI를 업데이트할 것입니다.
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

// 💡 StatelessWidget에서 StatefulWidget으로 변경
class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  // 💡 공유 인텐트 스트림 구독 객체
  StreamSubscription? _intentMediaStreamSubscription;

  // 💡 신규: 딥링크 처리를 위한 변수
  late AppLinks _appLinks;
  StreamSubscription<Uri>? _linkSubscription;

  @override
  void initState() {
    super.initState();
    _initSharingIntent(); // 기존 공유 인텐트
    _initDeepLinks();     // 💡 신규 딥링크 리스너 초기화
  }

  // 💡 신규 추가된 딥링크 초기화 함수
  void _initDeepLinks() {
    _appLinks = AppLinks();

    // 1. 앱이 완전히 종료된 상태(콜드 스타트)에서 딥링크로 켜질 때
    _appLinks.getInitialLink().then((uri) {
      if (uri != null) _handleDeepLink(uri);
    });

    // 2. 앱이 메모리에 있는 상태(백그라운드)에서 딥링크 클릭 시
    _linkSubscription = _appLinks.uriLinkStream.listen((uri) {
      _handleDeepLink(uri);
    }, onError: (err) {
      debugPrint("🔗 [AppLinks] 딥링크 에러: $err");
    });
  }

  // 💡 딥링크 URL 파싱 로직
  void _handleDeepLink(Uri uri) {
    debugPrint("🔗 [AppLinks] 딥링크 수신: $uri");

    // 예: https://noticestorage.com/invite?ref=123 로 들어왔을 경우
    if (uri.path.contains('/invite')) {
      final referrerCode = uri.queryParameters['ref'];

      if (referrerCode != null && referrerCode.isNotEmpty) {
        debugPrint("🎁 추천인 코드 확인: $referrerCode");

        // 콜드 스타트 시 context가 null일 수 있으므로 로컬 저장소에 안전하게 보관합니다.
        // 회원가입 완료 후 이 값을 지워주면 됩니다.
        PreferencesService.saveReferrerCode(referrerCode);
      }
    }
  }



  void _initSharingIntent() {
    // 모바일 환경(안드로이드, iOS)에서만 공유 인텐트 활성화
    if (!kIsWeb && (Platform.isAndroid || Platform.isIOS)) {
      // 1. 앱이 메모리에 있는 상태(백그라운드)에서 공유 요청이 들어올 때
      _intentMediaStreamSubscription = ReceiveSharingIntent.instance
          .getMediaStream()
          .listen((List<SharedMediaFile> value) {
        if (value.isNotEmpty && value.first.type == SharedMediaType.text) {
          _handleSharedUrl(value.first.path);
        }
      }, onError: (err) {
        debugPrint("getIntentDataStream error: $err");
      });

      // 2. 앱이 완전히 종료된 상태(콜드 스타트)에서 공유 요청으로 앱이 켜질 때
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
        // 1. 외부에서 들어온 URL을 Provider에 보관
        context.read<NoticeProvider>().setPendingUrl(url);

        // 💡 2. NavigationProvider가 아닌 NoticeProvider의 탭 인덱스를 3(추가 탭)으로 변경!
        context.read<NoticeProvider>().setSelectedIndex(3);

        // 3. 메인 화면으로 돌아오기
        navigatorKey.currentState?.popUntil((route) => route.isFirst);
      }
    }
  }

  @override
  void dispose() {
    // 💡 Null-aware 연산자(?.)를 사용하여 윈도우 환경에서의 예외 발생 방지
    _intentMediaStreamSubscription?.cancel();
    _linkSubscription?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<SettingsProvider>().settings;

    return MaterialApp(
      navigatorKey: navigatorKey, // 💡 전역 키 연결 유지
      initialRoute: '/home',
      title: '센트리피전',
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