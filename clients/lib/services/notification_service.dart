import 'dart:convert';
import 'dart:io';
import 'dart:ui';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import '../main.dart';
import '../providers/notice_provider.dart';
import 'preferences_service.dart'; // 💡 [추가] 토큰 로드를 위해 필요
import 'package:flutter_dotenv/flutter_dotenv.dart';

@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
  debugPrint("Handling a background message: ${message.messageId}");
}

class NotificationService {
  static final NotificationService _instance = NotificationService._internal();
  factory NotificationService() => _instance;
  NotificationService._internal();

  final FlutterLocalNotificationsPlugin _localPlugin = FlutterLocalNotificationsPlugin();

  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  // 💡 백엔드 API 주소 (FastAPI 주소 확인)
  String get _apiUrl => 'http://${_ipAddress}/v1/user/fcm-token'; // 💡 기존 fcm-token에서 통합 주소로 변경 권장

  Future<void> init() async {
    const AndroidInitializationSettings androidSettings = AndroidInitializationSettings('pigeon_cutout');
    const DarwinInitializationSettings iOSSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );
    const InitializationSettings initSettings = InitializationSettings(
      android: androidSettings,
      iOS: iOSSettings,
    );

    await _localPlugin.initialize(
      initSettings,
      onDidReceiveNotificationResponse: (NotificationResponse details) {
        _handleMessage(details.payload);
        if (details.payload != null) {
          debugPrint("알림 클릭됨. 페이로드: ${details.payload}");
        }
      },
    );

    // 💡 [해결책 1] Android 알림 채널 명시적 생성 추가
    const AndroidNotificationChannel channel = AndroidNotificationChannel(
      'notice_store_updates', // id (아래 _showForegroundNotification의 id와 동일해야 함)
      '새 소식 알림', // name (사용자에게 보이는 채널 이름)
      description: '구독 중인 사이트의 새 소식 알림', // description
      importance: Importance.max,
    );

    await _localPlugin
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);

    // 💡 2. 플랫폼 분기 처리: Web이 아니면서 Windows인 경우 FCM 초기화 패스
    if (!kIsWeb && Platform.isWindows) {
      debugPrint("💻 Windows 플랫폼: FCM(푸시 알림)을 지원하지 않으므로 초기화를 건너뜁니다.");
      return; // 여기서 함수를 끝내서 _setupFCM()이 호출되지 않도록 방어
    }

    await _setupFCM();
  }

  Future<void> _setupFCM() async {
    FirebaseMessaging messaging = FirebaseMessaging.instance;
    NotificationSettings settings = await messaging.requestPermission(
      alert: true, badge: true, sound: true,
    );

    if (settings.authorizationStatus == AuthorizationStatus.authorized) {
      debugPrint('사용자가 알림 권한을 허용했습니다.');

      String? token = await messaging.getToken();
      if (token != null) {
        debugPrint('FCM Token: $token');
        await sendTokenToServer(token); // 💡 여기서 전송 (이미 로그인된 상태일 경우)
      }

      messaging.onTokenRefresh.listen((newToken) {
        debugPrint('FCM Token Refreshed: $newToken');
        sendTokenToServer(newToken);
      });

      FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

      FirebaseMessaging.onMessage.listen((RemoteMessage message) {
        debugPrint('포그라운드 메시지 수신: ${message.notification?.title}');
        _showForegroundNotification(message);

        // 1. 알림 데이터에서 신규 공지 리스트와 site_id 추출
        final String? rawNotices = message.data['new_notices'];
        final String? rawSiteId = message.data['site_id']; // 백엔드에서 보낸 ID

        final context = navigatorKey.currentContext;
        if (context == null) return;

        // 2. 신규 데이터와 유효한 ID가 모두 있는 경우 증분 업데이트(onFetchComplete) 수행
        if (rawNotices != null && rawSiteId != null) {
          try {
            final List<dynamic> decodedNotices = jsonDecode(rawNotices);
            final int? siteId = int.tryParse(rawSiteId); // 💡 String을 int로 안전하게 변환

            if (siteId != null) {
              debugPrint('🚀 증분 업데이트 실행: Site ID $siteId');
              Provider.of<NoticeProvider>(context, listen: false)
                  .onFetchComplete(List<Map<String, dynamic>>.from(decodedNotices), siteId);
            } else {
              // ID 변환 실패 시 전체 새로고침으로 폴백
              Provider.of<NoticeProvider>(context, listen: false).fetchNoticesFromServer();
            }
          } catch (e) {
            debugPrint('❌ FCM 데이터 파싱 에러: $e');
            Provider.of<NoticeProvider>(context, listen: false).fetchNoticesFromServer();
          }
        } else {
          // 3. 데이터가 없거나 형식이 다르면 기존처럼 전체 새로고침 수행
          debugPrint('🔄 데이터 불충분으로 전체 새로고침 수행');
          Provider.of<NoticeProvider>(context, listen: false).fetchNoticesFromServer();
        }
      });

      // 💡 [케이스 2] 앱이 완전히 종료(Terminated)된 상태에서 알림 클릭으로 앱 실행
      RemoteMessage? initialMessage = await FirebaseMessaging.instance.getInitialMessage();
      if (initialMessage != null) {
        _handleMessage(jsonEncode(initialMessage.data));
      }

      // 💡 [케이스 3] 앱이 백그라운드에 있을 때 알림 클릭 처리
      FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
        _handleMessage(jsonEncode(message.data));
      });
    }
  }

  /// 공통 라우팅 로직
  void _handleMessage(String? payload) {
    if (payload == null) return;

    try {
      final Map<String, dynamic> data = jsonDecode(payload);

      if (data['screen'] == 'subscriptions') {
        debugPrint('🚀 구독 탭으로 인덱스 전환 시도');

        // 💡 [수정] 앱이 갓 켜진 상태(Terminated)에서도 안전하게 작동하도록 딜레이 추가
        Future.delayed(const Duration(milliseconds: 500), () {
          final context = navigatorKey.currentContext;
          if (context != null) {
            // 💡 현재 MainWrapper의 인덱스를 관리하는 NoticeProvider를 호출합니다.
            // 구독 탭은 리스트의 1번 인덱스입니다.
            Provider.of<NoticeProvider>(context, listen: false).setSelectedIndex(1);

            // 만약 다른 상세 페이지가 열려있다면 닫고 메인(MainWrapper)으로 돌아옵니다.
            navigatorKey.currentState?.popUntil((route) => route.isFirst);
          }
        });
      }
    } catch (e) {
      debugPrint('❌ 라우팅 에러: $e');
    }
  }

  /// 💡 [신규 추가] 로그인 성공 직후 AuthProvider에서 호출할 함수
  /// 기기의 토큰을 다시 가져와서 서버에 강제 동기화합니다. [cite: 2026-02-22]
  Future<void> syncTokenAfterLogin() async {
    try {
      String? token = await FirebaseMessaging.instance.getToken();
      if (token != null) {
        debugPrint('🔑 [FCM] 로그인 직후 토큰 동기화 시도...');
        await sendTokenToServer(token);
      }
    } catch (e) {
      debugPrint('❌ [FCM] 토큰 동기화 실패: $e');
    }
  }

  /// 기기 고유 식별자와 타입을 가져오는 공통 함수 [cite: 2026-03-10]
  Future<Map<String, String>> getDeviceInfo() async {
    final DeviceInfoPlugin deviceInfo = DeviceInfoPlugin();
    String deviceId = '';
    String deviceType = '';

    if (Platform.isAndroid) {
      final androidInfo = await deviceInfo.androidInfo;
      deviceId = androidInfo.id; // SSAID (Android ID) [cite: 2026-03-10]
      deviceType = 'android';
    } else if (Platform.isIOS) {
      final iosInfo = await deviceInfo.iosInfo;
      deviceId = iosInfo.identifierForVendor ?? 'unknown_ios'; // IDFV [cite: 2026-03-10]
      deviceType = 'ios';
    }

    return {
      'device_id': deviceId,
      'device_type': deviceType,
    };
  }

  /// 백엔드 서버로 FCM 토큰 및 기기 정보를 전송하여 세션을 업데이트합니다. [cite: 2026-03-10]
  Future<void> sendTokenToServer(String token) async {
    try {
      final String? accessToken = await PreferencesService.getAuthToken();

      if (accessToken == null || accessToken.isEmpty) {
        debugPrint('ℹ️ [FCM] 인증 토큰이 없어 전송을 중단합니다.');
        return;
      }

      // 1. 리팩토링: 공통 함수를 사용하여 기기 정보 추출 [cite: 2026-03-10]
      final deviceInfo = await getDeviceInfo();

      // 2. 서버에 POST 요청 전송 (1:N 기기 관리 구조 지원) [cite: 2026-03-10]
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        body: jsonEncode({
          "fcm_token": token,
          "device_id": deviceInfo['device_id'],
          "device_type": deviceInfo['device_type'],
        }),
      );

      if (response.statusCode == 200) {
        debugPrint('✅ [FCM] 토큰 및 기기 정보 동기화 성공!');
      } else {
        debugPrint('❌ [FCM] 전송 실패: ${response.statusCode} - ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ [FCM] 전송 중 에러 발생: $e');
    }
  }

  Future<void> deleteTokenOnLogout() async {
    try {
      final String? accessToken = await PreferencesService.getAuthToken();
      if (accessToken == null) return;

      final DeviceInfoPlugin deviceInfo = DeviceInfoPlugin();
      String deviceId = '';

      if (Platform.isAndroid) {
        deviceId = (await deviceInfo.androidInfo).id;
      } else if (Platform.isIOS) {
        deviceId = (await deviceInfo.iosInfo).identifierForVendor ?? '';
      }

      final response = await http.delete(
        Uri.parse(_apiUrl), // @router.delete("/fcm-token") 주소
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        body: jsonEncode({"device_id": deviceId}),
      );

      if (response.statusCode == 200) {
        debugPrint('✅ [FCM] 서버에서 현재 기기 토큰 삭제 성공');
      }
    } catch (e) {
      debugPrint('❌ [FCM] 로그아웃 시 토큰 삭제 요청 실패: $e');
    }
  }


  Future<void> _showForegroundNotification(RemoteMessage message) async {
    RemoteNotification? notification = message.notification;
    AndroidNotification? android = message.notification?.android;

    if (notification != null && android != null) {
      const AndroidNotificationDetails androidDetails = AndroidNotificationDetails(
        'notice_store_updates',
        '새 소식 알림',
        channelDescription: '구독 중인 사이트의 새 소식 알림',
        importance: Importance.max,
        priority: Priority.high,
        icon: 'pigeon_cutout',
        color: Color(0xFFF5F5F5),
      );

      const NotificationDetails details = NotificationDetails(
        android: androidDetails,
        iOS: DarwinNotificationDetails(presentAlert: true, presentBadge: true, presentSound: true),
      );

      await _localPlugin.show(
        notification.hashCode,
        notification.title,
        notification.body,
        details,
        payload: jsonEncode(message.data),
      );
    }
  }
}