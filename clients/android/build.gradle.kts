allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
//subprojects {
//    project.evaluationDependsOn(":app")
//}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}

// 플러그인들이 요구하는 Java/Kotlin 버전을 우리 프로젝트(Java 17)에 강제로 맞춥니다.
subprojects {
    afterEvaluate {
        // 1. Android 플러그인의 내부 Java 컴파일 옵션까지 17로 덮어쓰기
        extensions.findByName("android")?.let { androidExt ->
            (androidExt as com.android.build.gradle.BaseExtension).compileOptions.apply {
                sourceCompatibility = JavaVersion.VERSION_17
                targetCompatibility = JavaVersion.VERSION_17
            }
        }

        // 2. 표준 Java 컴파일 태스크 17로 강제 설정
        tasks.withType<JavaCompile>().configureEach {
            sourceCompatibility = "17"
            targetCompatibility = "17"
        }

        // 3. Kotlin 컴파일 타겟 17로 강제 설정
        tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
            compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
}