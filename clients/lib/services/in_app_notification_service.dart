import 'package:flutter/material.dart';

/// 어느 탭이나 화면에 있더라도 등록 결과를 같은 ScaffoldMessenger에 표시합니다.
class InAppNotificationService {
  InAppNotificationService._();

  static final GlobalKey<ScaffoldMessengerState> messengerKey =
  GlobalKey<ScaffoldMessengerState>();

  static void show(
      String message, {
        bool isError = false,
        bool isSuccess = false,
      }) {
    final messenger = messengerKey.currentState;
    if (messenger == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final mountedMessenger = messengerKey.currentState;
        if (mountedMessenger != null) {
          _show(
            mountedMessenger,
            message,
            isError: isError,
            isSuccess: isSuccess,
          );
        }
      });
      return;
    }

    _show(messenger, message, isError: isError, isSuccess: isSuccess);
  }

  static void _show(
      ScaffoldMessengerState messenger,
      String message, {
        required bool isError,
        required bool isSuccess,
      }) {
    // 진행 안내가 남아 있더라도 최종 성공/실패 결과를 즉시 보여줍니다.
    messenger.clearSnackBars();
    messenger.showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError
            ? const Color(0xFFA59971)
            : (isSuccess ? Colors.green : Colors.black87),
        behavior: SnackBarBehavior.floating,
        duration: Duration(seconds: isError ? 5 : 3),
      ),
    );
  }
}
