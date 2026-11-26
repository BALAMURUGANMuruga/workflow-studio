import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { User } from '../models/user.model';

@Injectable({
  providedIn: 'root'
})
export class UserService {

  private http = inject(HttpClient);

  private readonly API_URL =
    '/operations-api/api/users';

  // Fetch the user collection for the management UI.
  getUsers(): Observable<User[]> {
    return this.http.get<User[]>(this.API_URL);
  }

  // Fetch one user using its identifier.
  getUser(id: string): Observable<User> {
    return this.http.get<User>(
      `${this.API_URL}/${id}`
    );
  }

  // Send user data to the account service and return the created record.
  createUser(user: User): Observable<User> {
    return this.http.post<User>(
      this.API_URL,
      user
    );
  }

 


  getUserById(id: string) {
  return this.http.get<any>(
    `${this.API_URL}/${id}`
  );
}

updateUser(id: string, data: any) {
  return this.http.put<any>(
    `${this.API_URL}/${id}`,
    data
  );
}


  // Request deletion of the selected user.
  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(
      `${this.API_URL}/${id}`
    );
  }

 
}