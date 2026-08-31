SELECT count(*)
FROM cast_info, keyword, movie_keyword, name, title
WHERE cast_info.note = '(as Dick O''Harry)'
  AND name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id;
