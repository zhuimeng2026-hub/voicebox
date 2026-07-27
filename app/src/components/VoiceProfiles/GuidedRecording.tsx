import { Mic, RefreshCw, Check, AlertTriangle, Info } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CHINESE_SAMPLE_PROMPT } from '@/lib/constants/samplePrompts';
import { useAudioRecording } from '@/lib/hooks/useAudioRecording';
import { useSampleQuality } from '@/lib/hooks/useSampleQuality';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import type { SampleQualityResult } from '@/lib/api/types';

interface GuidedRecordingProps {
  profileId: string;
  onSampleReady: (
    blob: Blob,
    referenceText: string,
    quality: SampleQualityResult,
  ) => void;
  onCancel: () => void;
}

type Stage = 'prompt' | 'recording' | 'analyzing' | 'result_pass' | 'result_fail';

export function GuidedRecording({
  profileId,
  onSampleReady,
  onCancel,
}: GuidedRecordingProps) {
  const { t } = useTranslation();
  const [stage, setStage] = useState<Stage>('prompt');
  const [qualityResult, setQualityResult] = useState<SampleQualityResult | null>(null);
  const recordingBlobRef = useRef<Blob | null>(null);

  const prompt = CHINESE_SAMPLE_PROMPT;

  const { duration, error: recError, startRecording, stopRecording } =
    useAudioRecording({
      maxDurationSeconds: 29,
      onRecordingComplete: (blob) => {
        recordingBlobRef.current = blob;
        setStage('analyzing');
        analyzeMutation.mutate({
          profileId,
          audioBlob: blob,
          referenceText: prompt.text,
        });
      },
    });

  const analyzeMutation = useSampleQuality();

  // React to mutation result
  useEffect(() => {
    if (analyzeMutation.isSuccess && analyzeMutation.data) {
      const result = analyzeMutation.data;
      setQualityResult(result);
      setStage(result.passed ? 'result_pass' : 'result_fail');
    }
  }, [analyzeMutation.isSuccess, analyzeMutation.data]);

  // React to mutation error
  useEffect(() => {
    if (analyzeMutation.isError) {
      // Treat error as fail with generic message
      const result: SampleQualityResult = {
        passed: false,
        score: 0,
        duration_seconds: 0,
        issues: [
          analyzeMutation.error?.message ||
            '分析失败，请重试',
        ],
        warnings: [],
        metrics: {},
      };
      setQualityResult(result);
      setStage('result_fail');
    }
  }, [analyzeMutation.isError, analyzeMutation.error]);

  // Show recording errors
  useEffect(() => {
    if (recError) {
      const result: SampleQualityResult = {
        passed: false,
        score: 0,
        duration_seconds: 0,
        issues: [recError],
        warnings: [],
        metrics: {},
      };
      setQualityResult(result);
      setStage('result_fail');
    }
  }, [recError]);

  const handleRetry = useCallback(() => {
    analyzeMutation.reset();
    setQualityResult(null);
    recordingBlobRef.current = null;
    setStage('prompt');
  }, [analyzeMutation]);

  const handleAccept = useCallback(() => {
    if (recordingBlobRef.current && qualityResult) {
      onSampleReady(recordingBlobRef.current, prompt.text, qualityResult);
    }
  }, [prompt.text, qualityResult, onSampleReady]);

  return (
    <div className="flex flex-col gap-4">
      {/* Stage: Prompt — show text, ready to record */}
      {stage === 'prompt' && (
        <>
          <div className="rounded-lg border bg-muted/30 p-4">
            <p className="text-sm text-muted-foreground mb-2">
              {t('guidedRecording.readAloud')}
            </p>
            <p className="text-lg leading-relaxed tracking-wide select-none">
              {prompt.text}
            </p>
          </div>
          <div className="flex gap-3">
            <Button
              onClick={() => {
                void startRecording();
                setStage('recording');
              }}
              className="gap-2"
            >
              <Mic className="w-4 h-4" />
              {t('guidedRecording.startRecording')}
            </Button>
            <Button variant="ghost" onClick={onCancel}>
              {t('common.cancel')}
            </Button>
          </div>
        </>
      )}

      {/* Stage: Recording — show countdown, stop button */}
      {stage === 'recording' && (
        <>
          <div className="rounded-lg border bg-muted/30 p-4 opacity-60">
            <p className="text-lg leading-relaxed tracking-wide">{prompt.text}</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <Progress value={(duration / 29) * 100} />
            </div>
            <span className="text-sm tabular-nums w-12 text-right">
              {Math.ceil(duration)}s
            </span>
          </div>
          <Button
            onClick={() => void stopRecording()}
            variant="destructive"
            className="gap-2"
            disabled={duration < 2}
          >
            <Mic className="w-4 h-4" />
            {t('guidedRecording.stopRecording')}
          </Button>
        </>
      )}

      {/* Stage: Analyzing — spinner */}
      {stage === 'analyzing' && (
        <div className="flex flex-col items-center gap-4 py-8">
          <RefreshCw className="w-8 h-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {t('guidedRecording.analyzing')}
          </p>
        </div>
      )}

      {/* Stage: Result — FAIL */}
      {stage === 'result_fail' && qualityResult && (
        <>
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4">
            <div className="flex items-start gap-2 mb-3">
              <AlertTriangle className="w-5 h-5 text-destructive mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-destructive">
                  {t('guidedRecording.qualityFailed')}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t('guidedRecording.scoreLabel')}:{' '}
                  {Math.round(qualityResult.score * 100)}%
                </p>
              </div>
            </div>
            {qualityResult.issues.length > 0 && (
              <ul className="space-y-1 mb-3">
                {qualityResult.issues.map((issue, i) => (
                  <li
                    key={i}
                    className="text-sm text-destructive flex gap-2"
                  >
                    <span>&bull;</span> {issue}
                  </li>
                ))}
              </ul>
            )}
            {qualityResult.warnings.length > 0 && (
              <ul className="space-y-1">
                {qualityResult.warnings.map((w, i) => (
                  <li
                    key={i}
                    className="text-sm text-amber-600 dark:text-amber-400 flex gap-2"
                  >
                    <Info className="w-4 h-4 shrink-0 mt-0.5" />
                    {w}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex gap-3">
            <Button
              onClick={handleRetry}
              variant="outline"
              className="gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              {t('guidedRecording.retry')}
            </Button>
            <Button onClick={handleAccept} variant="secondary">
              {t('guidedRecording.acceptAnyway')}
            </Button>
          </div>
        </>
      )}

      {/* Stage: Result — PASS */}
      {stage === 'result_pass' && qualityResult && (
        <>
          <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-950 p-4">
            <div className="flex items-start gap-2">
              <Check className="w-5 h-5 text-green-600 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-green-700 dark:text-green-400">
                  {t('guidedRecording.qualityPassed')}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t('guidedRecording.scoreLabel')}:{' '}
                  {Math.round(qualityResult.score * 100)}%
                  {' · '}
                  {t('guidedRecording.durationLabel')}:{' '}
                  {qualityResult.duration_seconds.toFixed(1)}s
                </p>
              </div>
            </div>
          </div>
          <div className="flex gap-3">
            <Button onClick={handleAccept} className="gap-2">
              <Check className="w-4 h-4" />
              {t('guidedRecording.useThisSample')}
            </Button>
            <Button onClick={handleRetry} variant="ghost">
              {t('guidedRecording.retry')}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
