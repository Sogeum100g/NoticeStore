import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    // START: FlutterFire Configuration
    id("com.google.gms.google-services")
    // END: FlutterFire Configuration
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// 1. key.properties 파일을 읽어오는 로직
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    namespace = "com.noticestore.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.noticestore.app"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // 2. signingConfigs를 buildTypes보다 먼저 정의해야 함
    signingConfigs {
        create("release") {
            keyAlias = keystoreProperties.getProperty("key.alias.name")
            keyPassword = keystoreProperties.getProperty("key.alias.password")
            storeFile = keystoreProperties.getProperty("key.store.file")?.let { file(it) }
            storePassword = keystoreProperties.getProperty("key.store.password")
        }
    }

    buildTypes {
        getByName("release") {
            // debug 대신 위에서 만든 release 설정을 사용하도록 수정
            signingConfig = signingConfigs.getByName("release")

            isMinifyEnabled = false // 필요에 따라 설정
            isShrinkResources = false
        }
    }

    // 3. APK 파일명 변경 로직 (Kotlin DSL 문법으로 수정)
    applicationVariants.all {
        val variant = this
        variant.outputs.all {
            val output = this as com.android.build.gradle.internal.api.ApkVariantOutputImpl
            val projectName = "센트리피전"
            val currentVersionName = variant.versionName

            if (variant.buildType.name == "release") {
                output.outputFileName = "${projectName}_v${currentVersionName}.apk"
            }
        }
    }
}


flutter {
    source = "../.."
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.0.3")
}

// [수정됨] Error 1 해결을 위해 최신 compilerOptions DSL을 사용하여 jvmTarget 설정
tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}