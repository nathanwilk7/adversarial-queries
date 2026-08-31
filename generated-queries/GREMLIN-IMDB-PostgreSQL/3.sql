SELECT count(*)
FROM aka_name, cast_info, char_name, keyword, movie_keyword, name, title
WHERE cast_info.note = '(as Dick O''Harry)'
  AND char_name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id;
