import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize, Subscription } from 'rxjs';
import { ExceptionAssistService, ExceptionCode, ExceptionMessage } from '../../services/exception-assist.service';



interface ChatMessage {
  role: 'bot';
  text: string;
  inputXml?: string;
  errorXml?: string;
}

@Component({
  selector: 'app-exception-assist',
  standalone: true,
  imports: [  CommonModule,
    FormsModule],
  templateUrl: './exception-assist.html',
  styleUrl: './exception-assist.scss',
})
export class ExceptionAssist implements OnInit, OnDestroy {

  codes: ExceptionCode[] = [];
  selectedCode: string | null = null;
  messages: ChatMessage[] = [];

  isEnabled = false;
  isStreaming = false;
  isPaused = false;
  isLoading = false;
  errorMessage = '';

  private streamSubscription?: Subscription;

  constructor(private service: ExceptionAssistService) {}

  ngOnInit(): void {
    this.loadCodes();
  }

  loadCodes(): void {
    this.isLoading = true;
    this.errorMessage = '';

    this.service.getExceptionCodes()
      .pipe(finalize(() => this.isLoading = false))
      .subscribe({
        next: data => this.codes = data,
        error: err => {
          console.error('Failed to load exception codes', err);
          this.errorMessage =
            'Unable to load exception codes. Check the backend connection.';
        }
      });
  }

  startStream(): void {
    if (!this.selectedCode || this.isStreaming) {
      return;
    }

    this.messages = [];
    this.errorMessage = '';
    this.isStreaming = true;
    this.isPaused = false;

    this.streamSubscription = this.service
      .startStream(this.selectedCode)
      .subscribe({
        next: (data: ExceptionMessage) => {
          this.messages = [
            ...this.messages,
            {
              role: 'bot',
              text: data.message ?? '',
              inputXml: data.inputXml,
              errorXml: data.errorXml
            }
          ];

          if (data.message === 'Completed') {
            this.stopStream();
          }
        },
        error: err => {
          console.error('WebSocket error', err);
          this.errorMessage = 'WebSocket connection failed.';
          this.finishStream();
        },
        complete: () => this.finishStream()
      });
  }

  pauseStream(): void {
    if (!this.isStreaming || this.isPaused) {
      return;
    }

    this.service.control('pause').subscribe({
      next: () => this.isPaused = true,
      error: err => {
        console.error('Pause failed', err);
        this.errorMessage = 'Unable to pause processing.';
      }
    });
  }

  resumeStream(): void {
    if (!this.isStreaming || !this.isPaused) {
      return;
    }

    this.service.control('resume').subscribe({
      next: () => this.isPaused = false,
      error: err => {
        console.error('Resume failed', err);
        this.errorMessage = 'Unable to resume processing.';
      }
    });
  }

  stopStream(): void {
    this.service.stopStream();
    this.streamSubscription?.unsubscribe();
    this.finishStream();
  }

  private finishStream(): void {
    this.isStreaming = false;
    this.isPaused = false;
    this.streamSubscription = undefined;
  }

  ngOnDestroy(): void {
    this.service.stopStream();
    this.streamSubscription?.unsubscribe();
  }
}