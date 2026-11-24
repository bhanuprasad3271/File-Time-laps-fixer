package com.offline.mediadatefixer;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Button;
import android.widget.LinearLayout;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONArray;

public class MainActivity extends AppCompatActivity {

    private static final int REQ_LEGACY_STORAGE = 1001;
    private WebView webView;
    private LinearLayout permissionBanner;
    private boolean promptedOnce = false;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        permissionBanner = findViewById(R.id.permissionBanner);
        Button btnGrant = findViewById(R.id.btnGrantPermission);
        btnGrant.setOnClickListener(v -> requestStoragePermission());

        webView = findViewById(R.id.webView);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");

        updatePermissionUi();
        webView.loadUrl("file:///android_asset/index.html");

        if (!hasStoragePermission() && !promptedOnce) {
            promptedOnce = true;
            requestStoragePermission();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        updatePermissionUi();
        if (hasStoragePermission()) {
            webView.post(() -> webView.evaluateJavascript("if (window.onStorageReady) window.onStorageReady();", null));
        }
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        webView.evaluateJavascript("(window.handleAndroidBack ? window.handleAndroidBack() : false)", value -> {
            if (!"true".equals(value) && !isFinishing()) {
                MainActivity.super.onBackPressed();
            }
        });
    }

    private boolean hasStoragePermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            return Environment.isExternalStorageManager();
        }
        return ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void updatePermissionUi() {
        permissionBanner.setVisibility(hasStoragePermission() ? View.GONE : View.VISIBLE);
    }

    private void requestStoragePermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                Intent intent = new Intent(
                        Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:" + getPackageName())
                );
                startActivity(intent);
                return;
            } catch (Exception ignored) {
            }
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
                return;
            } catch (Exception ignored) {
            }
            try {
                Intent appSettings = new Intent(
                        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())
                );
                startActivity(appSettings);
                return;
            } catch (Exception ignored) {
            }
        }
        ActivityCompat.requestPermissions(
                this,
                new String[]{
                        Manifest.permission.READ_EXTERNAL_STORAGE,
                        Manifest.permission.WRITE_EXTERNAL_STORAGE
                },
                REQ_LEGACY_STORAGE
        );
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        updatePermissionUi();
        if (hasStoragePermission()) {
            webView.post(() -> webView.evaluateJavascript("if (window.onStorageReady) window.onStorageReady();", null));
        }
    }

    public class AndroidBridge {
        private PyObject pyModule() {
            return Python.getInstance().getModule("media_date_engine");
        }

        @JavascriptInterface
        public String getRootPath() {
            return Environment.getExternalStorageDirectory().getAbsolutePath();
        }

        @JavascriptInterface
        public boolean hasPermission() {
            return hasStoragePermission();
        }

        @JavascriptInterface
        public String listDirectory(String dirPath) {
            return pyModule().callAttr("list_directory", dirPath).toString();
        }

        @JavascriptInterface
        public String scanSelection(String selectedPathsJson, boolean recursive, String customRegex, boolean allowShortYear) {
            return pyModule().callAttr("scan_selection", selectedPathsJson, recursive, customRegex, allowShortYear).toString();
        }

        @JavascriptInterface
        public String applyUpdates(String itemsJson, String undoFolder) {
            return pyModule().callAttr("apply_updates", itemsJson, undoFolder).toString();
        }

        @JavascriptInterface
        public String applyBundleDate(String pathsJson, String dateTimeStr, String undoFolder) {
            return pyModule().callAttr("apply_bundle_date", pathsJson, dateTimeStr, undoFolder).toString();
        }

        @JavascriptInterface
        public String undoLastRun(String undoPath) {
            return pyModule().callAttr("undo_last_run", undoPath).toString();
        }

        @JavascriptInterface
        public String getFileDetails(String filePath) {
            return pyModule().callAttr("get_file_details", filePath).toString();
        }

        @JavascriptInterface
        public String saveFileDetails(String payloadJson) {
            return pyModule().callAttr("save_file_details", payloadJson).toString();
        }

        @JavascriptInterface
        public void refreshMediaStore(String pathsJson) {
            try {
                JSONArray arr = new JSONArray(pathsJson);
                String[] paths = new String[arr.length()];
                for (int i = 0; i < arr.length(); i++) {
                    paths[i] = arr.getString(i);
                }
                if (paths.length > 0) {
                    MediaScannerConnection.scanFile(MainActivity.this, paths, null, null);
                }
            } catch (Exception ignored) {
            }
        }
    }
}
