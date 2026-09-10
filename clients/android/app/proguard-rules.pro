# Flutter가 참조하지만 이 앱에서는 쓰지 않는 Play Core(딥링크 분할 설치) 클래스.
# 의존성에 포함되어 있지 않아 R8이 "Missing classes" 오류를 내므로 경고만 무시.
-dontwarn com.google.android.play.core.**

# @Keep 애노테이션이 붙은 클래스/멤버는 R8 축소 대상에서 제외.
-keep @androidx.annotation.Keep class * { *; }
-keepclassmembers class * {
    @androidx.annotation.Keep *;
}

# flutter_local_notifications: 예약 알림 재등록에 쓰이는 BroadcastReceiver/Service를
# 리플렉션으로 참조하므로 명시적으로 유지.
-keep class com.dexterous.flutterlocalnotifications.** { *; }

# Firebase Cloud Messaging 서비스/모델 클래스 유지.
-keep class com.google.firebase.messaging.** { *; }
